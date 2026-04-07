# Mizatube  
  
Python script and bookmarklet to handle my Granblue Fantasy [Youtube channel](https://www.youtube.com/user/Mizako03/videos) UI and thumbnail generation.  
  
Natural evolution of my older [GBFPIB](https://github.com/MizaGBF/GBFPIB) and [GBFTMR](https://github.com/MizaGBF/GBFTMR) projects, all in one.
  
# Requirements  
  
`pip install -r requirements.txt` to install all the modules. 
  
# Bookmarklet  
  
In your browser used for Granblue Fantasy, make a new bookmark.  
Edit it and, in the URL field, copy the content of `bookmarklet.txt`.  
  
For development purpose, `src/bookmarklet_code.js` contains the un-minified bookmarklet code.  
  
# Usage  
  
This script is only for use via command lines.  
  
## Register a character's EMP  
  
1. Go on a character EMP page.  
2. Press the bookmark.  
3. Run `mizatube.py`.  
  
## Register a character's Artifact  
  
1. Go on a character detail page (where stats, artifact (equipped or not) and skills are visible).  
2. Press the bookmark.  
3. Run `mizatube.py`.  

## Register a Boss  
  
1. Press the bookmark during a fight.  
2. Run `mizatube.py`. You'll be asked for a name.  
  
A boss can be registered during thumbnail generation too by passing the same data obtained from the bookmark.  
  
## Generate Party Images and thumbnail
  
1. On a party screen, open the estimate damage calculator.  
2. Press the bookmark.
3. Run `mizatube.py`.  
  
## Advanced Command Line usages  
  
Some command line arguments:  
- `-j/--json PATH`: Load the data from the given JSON file path instead from the clipboard.  
- `-i/--input I1 I2 I3 ... IN`: To pass a series of input that the script will read and use during thumbnail generation. For automation purpose.  
- `-nt/--nothumbnail`: You won't be asked if you want to generate a thumbnail.  
- `-sp/--skipparty`: You'll go straight to generate a thumbnail, without generating party images.  
- `-dr/--dryrun`: Images won't be written to disk (for debugging).  
- `-lb/--listbosses`: List the registered bosses.  
- `-tb/--testboss NAME`: Test to generate a boss.  
- `-cc/--cleancache`: Clear the cache folder.  
- `-ex/--exit`: Exit after parsing the arguments, without running the script (To use, for example, with `-cc`, `-lb` or `-tb`).  
  
## Thumbnail Templates  
  
Templates can be set in `json/template.json`.  
Possible types are:  
* `background`: Force the Background selection prompt to generate a background image.  
* `boss`: Similar to `background` but only generate the boss (No background image).  
* `party`: Check the clipboard for GBFPIB data to draw the party.  
* `autoinput`: Force the Auto Setting selection prompt.  
* `nminput`: Force the Unite and Fight / Dread Barrage / Records of the tens Fight / Nightmare icon selection prompt.  
* `textinput`: Force the Text input prompt.  
* `asset`: To display an asset. Filename must be set under the `asset` key. Local file names must follow `file:`, otherwise they will be requested from GBF CDN.  
  
Additionaly, all elements (except `background` and `boss`) can have the following values set:
* `position`: An array of two integer, X and Y offset relative to the anchor.  
* `anchor`: Default position of the element. Default is `topleft`.  
* `size`: Float, size multiplier.  
  
For `party`:
* `noskin`: Boolean, set to True to not display skins.  
* `mainsummon`: Boolean, set to True to only display the main summon used.  
  
For `textinput`:
* `fontcolor`: Array of 3 or 4 integers (RGB or RGBA values), color of the text (Default is white)  
* `gradient`: An array of 2 colors (array of 3 or 4 integers each for RGB or RGBA values), to color the text from top to bottom. It overrides `fontcolor`.
* `outlinecolor`: Array of 3 or 4 integers (RGB or RGBA values), color of the text outline (Default is red)  
* `fontsize`: Integer, text size (Default is 120)  
* `outlinesize`: Integer, size of the text outline (Default is 10)  
* `bold`: Boolean, set to True to draw bold text  
* `italic`: Boolean, set to True to draw italic text  
* `ljust`: Integer, to left align string lines  
* `rjust`: Integer, to right align string lines (Applied after `ljust`, if set)  
* `rotate`: An array of one or two elements: The angle (Integer, in degree) and an optional array of 2 integers (the rotation center).
* `maxwidth`: Integer, the maximum width of the text in pixel. The font size will auto reduce as long as it's higher.
* `multilinelimit`: Boolean, the font size will reduce if `true` and `\n` are found in the text.

# Note  
  
The project name is a reference to how people call my Yotuueb Channel.  