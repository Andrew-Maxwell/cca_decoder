CCA Decoder
=====

A Python script for decoding .cca (MMF 1.5) project files and exporting as Godot 3 scenes.

**Working:**

* Parse images and export as PNGs
* Parse ActiveItems and export as individual Godot scenes with animations
* Parse BackdropItems
* Parse level instances and instantiate Godot scenes (or Sprite2D nodes for BackdropItems)
* Translate grid-aligned instances into Godot tilesets

**Limitations:**

* No support for any logic
* Backgrounds (`LDrawbackItem`) are not parsed automatically. You must add them manually from the exported images.
* This project was created to parse a single game, solely through reverse engineering, without access to MMF 1.5
  Support for many other features is likely to be missing. e.g. I still don't know what all the item tags are.
* Godot integration is somewhat fragile. There seem to be subtle differences between the generated tscn files and
  the files Godot itself generates. Please follow the workflow below carefully.
* Probably lots of other bugs. Good luck!!

**Workflow**

*Important:* Follow these instructions carefully. Otherwise, you are likely to run into bugs.

Requires https://github.com/stevearc/godot_parser.

1. Place the script and the .cca file together in a directory.
2. Create an empty subdirectory and use **Godot 3.6** to create a new project in that subdirectory.
3. Run `cca_decoder.py <file.cca> -o <subdirectory>` with any other desired flags.
4. Allow Godot 3.6 to import the new scene files and assets and then **save immediately.** This is because the
   files created by the script are slightly different than the ones Godot creates itself. When you save, Godot
   overwrites the script files with its own files.
6. If you are using tilesets (`-t` option) and you wish to develop using Godot 4.x, you will run into this bug:
   https://github.com/godotengine/godot/issues/106563. To fix it:
   a. Open the project with Godot 4.2 first. Fix any broken dependencies. (If a scene's name is also a class name,
      Godot likes to rename it.)
   b. If your tiles are not 16x16 they may be invisible or jumbled. To fix it, select your tile**map** in each
      level. In the inspector pane, select the tile**set** and adjust the tile size.
      
      <img width="269" height="370" alt="image" src="https://github.com/user-attachments/assets/aa11a283-674b-4ff3-8f08-a8f0acea58e8" />
      
   c. In the bottom panel, select the Tile**Set** tab. Select your tileset in the menu to the left. In the second
      pane, under setup -> atlas, you must also adjust the "texture region size" to match your tile size.
      
      <img width="602" height="476" alt="image" src="https://github.com/user-attachments/assets/510ad645-9272-471d-8b90-d929cb995a5e" />
      
8. After fixing the tiles, save the project. You may now start working with the latest version of Godot (tested
   with 4.6 or 4.7.)

**Acknowledgements**

Thanks to Smidge from here: https://forums.sonicretro.org/threads/cca-and-gam-file-format-info-and-more.24592/
for documenting his own efforts to reverse-engineer the format, way back in 2011. It was a huge help!
(The original document is available on archive.org.)

**License**

Released under the MIT license.
