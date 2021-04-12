# Standalone TissUUmaps
Standalone TissUUmaps is [TissUUmaps](https://tissuumaps.research.it.uu.se/) running locally on your computer.

## Differences with TissUUmaps

### Image format
Standalone TissUUmaps can open images directly in TissUUmaps. By using a minimal deepzoom flask server, Standalone TissUUmaps removes the need for creating DZI files of every image.

Standalone TissUUmaps can read whole slide images in any format recognized by the [OpenSlide library](https://openslide.org/api/python/#openslide-python):
 * Aperio (.svs, .tif)
 * Hamamatsu (.ndpi, .vms, .vmu)
 * Leica (.scn)
 * MIRAX (.mrxs)
 * Philips (.tiff)
 * Sakura (.svslide)
 * Trestle (.tif)
 * Ventana (.bif, .tif)
 * Generic tiled TIFF (.tif)

plus classical images in any format recognized by the [PIL library](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html) (png, jpg, *etc.*)

> :warning: Warning: non pyramidal images will have to be loaded in RAM and will be read entirely for each generated tile. If you have big images, consider converting them in pyramidal format using VIPS.

## Installation

> Note that steps 1-4 are optional and can be replaced by installing a recent version of Python.

1. Install [Anaconda](https://docs.anaconda.com/anaconda/install/) (or miniconda).
1. Create a new conda environment from an Anaconda prompt:
    ```bash
	conda create --name tissuumaps python=3.8
    ```

1. Activate the new conda environment:
    ```bash
	conda activate tissuumaps
    ```

1. You should be in the tissuumaps environment:
    ```bash
	(tissuumaps) C:\
    ```

1. Install the Openslide library 
    >  * For windows:
    >    * Install [Microsoft Visual Studio Build Tools](https://visualstudio.microsoft.com/fr/downloads/).
    >    * Install the [openslide library](https://openslide.org/download/#windows-binaries).
    >    * Make sure the `bin` directory of openslide is in the `PATH` environment variable.
    >    * If the `libopenslide-0.dll` still fails to load, see fix [here](https://github.com/openslide/openslide-python/issues/51#issuecomment-656728468).
    >
    >  * For linux:
    >    * Install openslide using your distribution package (for example in Ubuntu : `apt-get install openslide-tools`).
    > 
    >  * For MacOs:
    >    * Install openslide using your MacPorts or Homebrew (`port install openslide` or `brew install openslide`).

1. Install python dependencies (openslide, flask, pillow, pyvips and PyQt5):
    ```bash
	pip install openslide-python flask pillow PyQtWebEngine
	conda install --channel conda-forge pyvips
    ```
    > In linux, check that you only have one installation of pillow:
    >   ```bash
    >   sudo pip uninstall pillow
    >   pip install pillow
    >   ```

1. Clone the FlaskTissUUmaps git repository or download in zip format and extract to a FlaskTissUUmaps folder
    ```bash
	git clone https://github.com/wahlby-lab/FlaskTissUUmaps --branch standalone
    ```

1. Go to the FlaskTissUUmaps folder and start Standalone TissUUmaps:
    ```bash
	cd FlaskTissUUmaps
    python TissUUmaps.py
    ```
