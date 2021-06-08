#!/usr/bin/env python
#
# flaskTissUUmaps - a minimal python server for TissUUmaps using Flask
#
# This library is free software; you can redistribute it and/or modify it
# under the terms of version 3.0 of the GNU General Public License
# as published by the Free Software Foundation.
#
# This library is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public
# License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this library; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

from collections import OrderedDict
from flask import Flask, abort, make_response, render_template, url_for,  request, Response, jsonify, send_from_directory

import pyvips

import threading, time
import json
from io import BytesIO
import openslide
from openslide import ImageSlide, OpenSlide, OpenSlideError, open_slide
from openslide.deepzoom import DeepZoomGenerator
import os
from optparse import OptionParser
from threading import Lock
from functools import wraps
import imghdr
import importlib
import glob

import PIL
PIL.Image.MAX_IMAGE_PIXELS = 93312000000

def check_auth(username, password):
    if username == "username" and password == "password":
        return True
    return False

def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
    'Could not verify your access level for that URL.\n'
    'You have to login with proper credentials', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        return f(*args, **kwargs) #Comment this line to add authentifaction
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

SLIDE_DIR = "/mnt/data/shared/"
SLIDE_CACHE_SIZE = 10
DEEPZOOM_FORMAT = 'jpeg'
DEEPZOOM_TILE_SIZE = 254
DEEPZOOM_OVERLAP = 1
DEEPZOOM_LIMIT_BOUNDS = True
DEEPZOOM_TILE_QUALITY = 75

FOLDER_DEPTH = 4
PLUGINS = []

app = Flask(__name__)
app.config.from_object(__name__)
app.config.from_envvar('DEEPZOOM_MULTISERVER_SETTINGS', silent=True)

class PILBytesIO(BytesIO):
    def fileno(self):
        '''Classic PIL doesn't understand io.UnsupportedOperation.'''
        raise AttributeError('Not supported')

class ImageConverter():
    def __init__(self, inputImage, outputImage):
        self.inputImage = inputImage
        self.outputImage = outputImage
    
    def convert (self):
        if not os.path.isfile(self.outputImage):
            def convertThread():
                try:
                    imgVips = pyvips.Image.new_from_file(self.inputImage)
                    minVal = imgVips.percent(10)
                    maxVal = imgVips.percent(99)
                    if minVal == maxVal:
                        minVal = 0
                        maxVal = 255
                    print ("minVal, maxVal", minVal, maxVal)
                    imgVips = (255.* (imgVips - minVal)) / (maxVal - minVal)
                    imgVips = (imgVips < 0).ifthenelse(0, imgVips)
                    imgVips = (imgVips > 255).ifthenelse(255, imgVips)
                    print ("minVal, maxVal", imgVips.min(), imgVips.max())
                    imgVips = imgVips.scaleimage()
                    imgVips.tiffsave(self.outputImage, pyramid=True, tile=True, tile_width=256, tile_height=256, properties=True, bitdepth=8)
                except: 
                    print ("Impossible to convert image using VIPS:")
                    import traceback
                    print (traceback.format_exc())
                self.convertDone = True
            self.convertDone = False
            threading.Thread(target=convertThread,daemon=True).start()
            while(not self.convertDone):
                time.sleep(0.02)
        return self.outputImage

class _SlideCache(object):
    def __init__(self, cache_size, dz_opts):
        self.cache_size = cache_size
        self.dz_opts = dz_opts
        self._lock = Lock()
        self._cache = OrderedDict()

    def get(self, path):
        with self._lock:
            if path in self._cache:
                # Move to end of LRU
                slide = self._cache.pop(path)
                self._cache[path] = slide
                return slide
        #try:
        osr = OpenSlide(path)
        #except:
        #    osr = ImageSlide(path)
            #Fix for 16 bits tiff files
            # if osr._image.getextrema()[1] > 256:
            #     osr._image = osr._image.point(lambda i:i*(1./256)).convert('L')
        
        slide = DeepZoomGenerator(osr, **self.dz_opts)
        slide.osr = osr
        
        slide.associated_images = {}
        for name, image in slide.osr.associated_images.items():
            slide.associated_images[name] = DeepZoomGenerator(ImageSlide(image))

        try:
            mpp_x = osr.properties[openslide.PROPERTY_NAME_MPP_X]
            mpp_y = osr.properties[openslide.PROPERTY_NAME_MPP_Y]
            slide.properties = osr.properties
            slide.mpp = (float(mpp_x) + float(mpp_y)) / 2
        except (KeyError, ValueError):
            slide.mpp = 0
        try:
            slide.properties = slide.properties
        except:
            slide.properties = osr.properties
        slide.tileLock = Lock()
        with self._lock:
            if path not in self._cache:
                while len(self._cache) >= self.cache_size:
                    self._cache.popitem(last=False)
                self._cache[path] = slide
        return slide


class _Directory(object):
    def __init__(self, basedir, relpath='', max_depth=4):
        self.name = os.path.basename(relpath)
        self.children = []
        if max_depth != 0:
            try:
                for name in sorted(os.listdir(os.path.join(basedir, relpath))):
                    if ".tissuumaps" in name:
                        continue
                    cur_relpath = os.path.join(relpath, name)
                    cur_path = os.path.join(basedir, cur_relpath)
                    if os.path.isdir(cur_path):
                        cur_dir = _Directory(basedir, cur_relpath, max_depth=max_depth-1)
                        if cur_dir.children:
                            self.children.append(cur_dir)
                    elif OpenSlide.detect_format(cur_path):
                        self.children.append(_SlideFile(cur_relpath))
                    elif imghdr.what(cur_path):
                        self.children.append(_SlideFile(cur_relpath))
                    elif ".tmap" in cur_path:
                        self.children.append(_SlideFile(cur_relpath))

                    
            except:
                pass


class _SlideFile(object):
    def __init__(self, relpath):
        self.name = os.path.basename(relpath)
        self.url_path = relpath.replace("\\","/")

def setup(app):
    app.basedir = os.path.abspath(app.config['SLIDE_DIR'])
    config_map = {
        'DEEPZOOM_TILE_SIZE': 'tile_size',
        'DEEPZOOM_OVERLAP': 'overlap',
        'DEEPZOOM_LIMIT_BOUNDS': 'limit_bounds',
    }
    opts = dict((v, app.config[k]) for k, v in config_map.items())
    app.cache = _SlideCache(app.config['SLIDE_CACHE_SIZE'], opts)

@app.before_first_request
def _setup():
    setup(app)

@app.errorhandler(404)
def page_not_found(e):
    # note that we set the 404 status explicitly
    return render_template('files.html', root_dir=_Directory(app.basedir, max_depth=app.config['FOLDER_DEPTH']), message="Impossible to load this file"), 404

def _get_slide(path):
    path = os.path.abspath(os.path.join(app.basedir, path))
    if not path.startswith(app.basedir + os.path.sep):
        # Directory traversal
        abort(404)
    if not os.path.exists(path):
        abort(404)
    try:
        slide = app.cache.get(path)
        slide.filename = os.path.basename(path)
        return slide
    except:
        if ".tissuumaps" in path:
            abort(404)
        try:
            newpath = os.path.dirname(path) + "/.tissuumaps/" + os.path.basename(path)
            if not os.path.isdir(os.path.dirname(path) + "/.tissuumaps/"):
                os.makedirs(os.path.dirname(path) + "/.tissuumaps/")
            path = ImageConverter(path,newpath).convert()
            #imgPath = imgPath.replace("\\","/")
            return _get_slide(path)
        except:
            import traceback
            print (traceback.format_exc())
            abort(404)

@app.route('/')
@requires_auth
def index():
    return render_template('files.html', root_dir=_Directory(app.basedir, max_depth=app.config['FOLDER_DEPTH']))

@app.route('/<path:path>')
@requires_auth
def slide(path):
    slide = _get_slide(path)
    slide_url = url_for('dzi', path=path)
    slide_properties = slide.properties
    
    associated_urls = dict((name, url_for('dzi_asso', path=path, associated_name=name)) for name in slide.associated_images.keys())
    folder_dir = _Directory(os.path.abspath(app.basedir)+"/",
                            os.path.dirname(path))
    return render_template('tissuumaps.html', plugins=app.config["PLUGINS"], associated=associated_urls, slide_url=slide_url, slide_filename=slide.filename, slide_mpp=slide.mpp, properties=slide_properties, root_dir=_Directory(app.basedir, max_depth=app.config['FOLDER_DEPTH']), folder_dir=folder_dir)

@app.route('/ping')
@requires_auth
def ping():
    return make_response("pong")

@app.route('/<path:path>.tmap', methods=['GET', 'POST'])
@requires_auth
def tmapFile(path):
    folder_dir = _Directory(os.path.abspath(app.basedir)+"/",
                            os.path.dirname(path))
    jsonFilename = os.path.abspath(os.path.join(app.basedir, path) + ".tmap")
    print (jsonFilename)
    if request.method == 'POST':
        state = request.get_json(silent=False)
        with open(jsonFilename,"w") as jsonFile:
            json.dump(state, jsonFile)
        return state
    else:
        if os.path.isfile(jsonFilename):
            try:
                with open(jsonFilename,"r") as jsonFile:
                    state = json.load(jsonFile)
            except:
                import traceback
                print (traceback.format_exc())
                abort(404)
        else:
            abort(404)
        return render_template('tissuumaps.html', plugins=app.config["PLUGINS"], jsonProject=state, root_dir=_Directory(app.basedir, max_depth=app.config['FOLDER_DEPTH']), folder_dir=folder_dir)

@app.route('/<path:path>.csv')
@requires_auth
def csvFile(path):
    completePath = os.path.abspath(os.path.join(app.basedir, path) + ".csv")
    directory = os.path.dirname(completePath)
    filename = os.path.basename(completePath)
    if os.path.isfile(completePath):
        return send_from_directory(directory, filename)
    else:
        abort(404)
    
@app.route('/<path:path>.json')
@requires_auth
def jsonFile(path):
    completePath = os.path.abspath(os.path.join(app.basedir, path) + ".json")
    directory = os.path.dirname(completePath)
    filename = os.path.basename(completePath)
    if os.path.isfile(completePath):
        return send_from_directory(directory, filename)
    else:
        abort(404)
    
@app.route('/<path:path>.dzi')
@requires_auth
def dzi(path):
    slide = _get_slide(path)
    format = app.config['DEEPZOOM_FORMAT']
    resp = make_response(slide.get_dzi(format))
    resp.mimetype = 'application/xml'
    return resp

@app.route('/<path:path>.dzi/<path:associated_name>')
@requires_auth
def dzi_asso(path,associated_name):
    slide = _get_slide(path)
    associated_image = slide.osr.associated_images[associated_name]
    dzg = DeepZoomGenerator(ImageSlide(associated_image))
    format = app.config['DEEPZOOM_FORMAT']
    resp = make_response(dzg.get_dzi(format))
    resp.mimetype = 'application/xml'
    return resp


@app.route('/<path:path>_files/<int:level>/<int:col>_<int:row>.<format>')
@requires_auth
def tile(path, level, col, row, format):
    slide = _get_slide(path)
    format = format.lower()
    #if format != 'jpeg' and format != 'png':
    #    # Not supported by Deep Zoom
    #    abort(404)
    try:
        with slide.tileLock:
            tile = slide.get_tile(level, (col, row))
    except ValueError:
        # Invalid level or coordinates
        abort(404)
    buf = PILBytesIO()
    tile.save(buf, format, quality=app.config['DEEPZOOM_TILE_QUALITY'])
    resp = make_response(buf.getvalue())
    resp.mimetype = 'image/%s' % format
    resp.cache_control.max_age = 1209600
    resp.cache_control.public = True
    return resp

@app.route('/<path:path>.dzi/<path:associated_name>_files/<int:level>/<int:col>_<int:row>.<format>')
@requires_auth
def tile_asso(path, associated_name, level, col, row, format):
    slide = _get_slide(path).associated_images[associated_name]
    format = format.lower()
    if format != 'jpeg' and format != 'png':
        # Not supported by Deep Zoom
        abort(404)
    try:
        tile = slide.get_tile(level, (col, row))
    except ValueError:
        # Invalid level or coordinates
        abort(404)
    buf = PILBytesIO()
    tile.save(buf, format, quality=app.config['DEEPZOOM_TILE_QUALITY'])
    resp = make_response(buf.getvalue())
    resp.mimetype = 'image/%s' % format
    return resp

def load_plugin(name):
    mod = importlib.import_module("."+name,package="plugins")
    return mod

@app.route('/plugin/<path:pluginName>.js')
def runPlugin(pluginName):
    directory = "plugins"
    filename = pluginName + ".js"
    completePath = os.path.abspath(os.path.join(directory, pluginName + ".js"))
    print (completePath)
    if os.path.isfile(completePath):
        return send_from_directory(directory, filename)
    else:
        abort(404)

@app.route('/plugin/<path:pluginName>/<path:method>', methods=['GET', 'POST'])
@requires_auth
def pluginJS(pluginName, method):
    print ("runPlugin", pluginName, method)
    print (request.method)
    
    pluginModule = load_plugin(pluginName)
    pluginInstance = pluginModule.Plugin(app)
    pluginMethod = getattr(pluginInstance, method)
    if request.method == 'POST':
        content = request.get_json(silent=False)
        return pluginMethod(content)
    else:
        content = request.args
        return pluginMethod(content)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'misc/favicon.ico', mimetype='image/vnd.microsoft.icon')


for module in glob.glob("plugins/*.py"):
    if "__init__.py" in module:
        continue
    app.config["PLUGINS"].append(os.path.splitext(os.path.basename(module))[0])  
print ("Plugins:", app.config["PLUGINS"])  

if __name__ == '__main__':
    parser = OptionParser(usage='Usage: %prog [options] [slide-directory]')
    parser.add_option('-B', '--ignore-bounds', dest='DEEPZOOM_LIMIT_BOUNDS',
                default=False, action='store_false',
                help='display entire scan area')
    parser.add_option('-c', '--config', metavar='FILE', dest='config',
                help='config file')
    parser.add_option('-d', '--debug', dest='DEBUG', action='store_true',
                help='run in debugging mode (insecure)')
    parser.add_option('-e', '--overlap', metavar='PIXELS',
                dest='DEEPZOOM_OVERLAP', type='int',
                help='overlap of adjacent tiles [1]')
    parser.add_option('-f', '--format', metavar='{jpeg|png}',
                dest='DEEPZOOM_FORMAT',
                help='image format for tiles [jpeg]')
    parser.add_option('-l', '--listen', metavar='ADDRESS', dest='host',
                default='127.0.0.1',
                help='address to listen on [127.0.0.1]')
    parser.add_option('-p', '--port', metavar='PORT', dest='port',
                type='int', default=5000,
                help='port to listen on [5000]')
    parser.add_option('-Q', '--quality', metavar='QUALITY',
                dest='DEEPZOOM_TILE_QUALITY', type='int',
                help='JPEG compression quality [75]')
    parser.add_option('-s', '--size', metavar='PIXELS',
                dest='DEEPZOOM_TILE_SIZE', type='int',
                help='tile size [254]')
    parser.add_option('-D', '--depth', metavar='LEVELS',
                dest='FOLDER_DEPTH', type='int',
                help='folder depth search for opening files [4]')

    (opts, args) = parser.parse_args()
    # Load config file if specified
    if opts.config is not None:
        app.config.from_pyfile(opts.config)

    # Overwrite only those settings specified on the command line
    for k in dir(opts):
        if not k.startswith('_') and getattr(opts, k) is None:
            delattr(opts, k)
    app.config.from_object(opts)
    # Set slide directory
    try:
        app.config['SLIDE_DIR'] = args[0]
    except IndexError:
        pass

    print ("Plugins:", app.config["PLUGINS"])  
    app.run(host=opts.host, port=opts.port, threaded=True)
