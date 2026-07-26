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
* This project was created to parse a single game, Within a Deep Forest, solely through reverse engineering, without access to MMF 1.5.
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

**Dev Retrospective**

There have been a couple of previous efforts to do something similar. The best one I found was here: https://forums.sonicretro.org/threads/cca-and-gam-file-format-info-and-more.24592/ which was able to output some of the assets, but it put them all in a single huuuuge spritesheet. Also all of the tilesets and backgrounds were missing - only character sprites were visible. I figured maybe I could do better and Smidge documented everything he found so that helped a lot.

The first couple of weekends were just spent decoding the file format, I used this software called ImHex which lets you define and parse custom structures in binary files. The first structure I figured out myself was the sprite palette (not actually used in WaDF) which is just like 1024 basic colors. I programmed imhex to parse the colors and display each palette entry in the correct color so that was pretty cool.

Images came next, the images are basically in one big block at the start of the file. Each one uses RLE (run length encoding) which was documented by Smidge. RLE is pretty cool, basically it just means if you have 100 black pixels then you store that as 100 * {black} instead of {black, black, black... } I remember some images had an extra "terminator" at the end of each row, and others did not. I had to figure out whether to include the terminator or not based on whether the total length of the RLE data matched the width * height of the image. Probably there was also a flag somewhere which would indicate that, but I couldn't find it. Getting all the images dumped as PNGs was another big "a-ha" moment. Oddly enough it included a lot of images that ccarip did not include, including some alternate assets that never made it into the final game.

I started out using Python and after that just stuck with it, which had upsides and downsides. I am also familiar with C++ and in some sense C++ actually has better native deserialization syntax using the << operator. (I assume MMF1.5 was written in C or C++ given the age.) With Python I had to write some of my own deserialization primitives but probably there was a nice library for that which I was just too lazy to find, I don't know. On the other hand Python has a nice Godot scene manipulation library and I suspect that writing that in C++ would have been a lot more effort than writing the deserialization in Python, so maybe it was the right choice after all.

Lots of time just spent scrolling through the entire file, learning my way around. There are various keywords scattered around so it's not totally unintelligible. I actually used the WaDF secrets file most of the time since it was a lot smaller and more manageable. Once I figured out the structure of e.g. images, items, or sprites, I could define a custom object for that and ImHex would highlight that object with different fields in different colors. So as I learned more the file became more and more color-coded and the big gaps where I didn't know anything got smaller. It was pretty satisfying.

After the images block comes the levels, each level has a list of items (objects/blueprints similar to Godot scenes) and instances (of the item.) ActiveItems had an animation format which was already documented by Smidge - just indexing into the list of images by image ID, which was pretty straightforward. BackdropItems also had an image ID which was under a different header, but not too hard to find either. It turns out that Smidge had not done that, which is why all the tilesets were missing from the ccarip output.

Instances weren't too bad either at first. Each instance was 32 bytes - something like

```
word: “Inst”
word: X position
word: Y position
word: Instance ID
word: ?
word: ?
word: Item ID (?)
word: 0xFFFFFFFF
```

The two ? were nearly always 0 so I ignored them. I could tell that the second to last was the item ID because it was the same for similar objects (e.g. in the secrets menu.) But it took me forever to figure out how it mapped to the item. It didn't match raw indexes into the items as an array, and it didn't match any of the fields in the item either. I spent a long time looking for a mapping between these mystery values and any sort of field in the item object. I actually gave up on the project for a while, but when I came back I realized that it was a field in the item object but it was a *different* field for ActiveItems and BackdropItems. After understanding that and adding Godot parser I was able to output the entire thing as a Godot scene which was another big milestone. But at first there were some problems with the positioning of the objects so all of the walls looked really wonky at first. Eventually I think I traced it back to the offset/hotspot within each image. Basically the hotspot lets you define an custom origin for the image - so the image will display offset from its actual position. I wasn't handling that correctly somehow.

Even after I got that fixed, every single tile was still a separate instance in Godot. I don't know if this was standard practice for MMF1.5 or if this is what Nifflas meant when he said the source was "old and embarrassing." In addition he had separate objects on top of every tile which indicated collisions. This worked out to 10-30k separate instances on the upper end and it really made Godot bog down. So I added a feature to detect when instances were aligned to a grid of a configurable size (WaDF used 24) and copy the image into a tileset (without trying to make it look pretty) and replace it with an instance in a Godot tileset. Godot tilesets were a huge headache. They changed the tileset format between 3.x and 4.x, and sometime after 4.2 the converter between the two formats also broke. So if you want to use the tilesets in 4.7 you have to generate the project in 3.x (because that's what the Godot python library I was using supports,) then open it in 4.2 and fix the tiles and then save it, and then you can open it in 4.6. I also tried outputting the tileset in 4.x format natively, but I could not figure it out for the life of me so I gave up.

There was another issue. In MMF1.5 all instances are in a single order where later instances are on top of earlier ones. Godot additionally has another ordering scheme called z-indexes where multiple objects can have the same z-index. All the tiles need to be at the same z-index, but for some object (e.g. a tree) some tiles could have been originally behind the tree, while others were in front. There's no way to represent that in Godot, so I didn't try. I just ignored converting any instances which overlap an instance I'd already converted to a tile. But this caused a bunch of problems which I had to go around fixing manually, where the ordering between the non-converted and the tile instance would be wrong. Often there would be two instances at the same tile location, and one would get converted to a tile and then the other would be a sprite that actually went behind it. I ended up checking if the entire instance was opaque and if it was, replacing the first tile at that location, and that eliminated about 90% of the errors (especially the really hard ones which involved placing tiles manually -- since the tileset is all jumbled, and all the tiles look really similar except for one pixel at the edge, this was a huge pain in the ass.) Once I had the tileset working I could just define a collision layer for it and then I could delete all the collision objects Nifflas used, which made things much cleaner.

The only other thing I can remember is that the hotspots bit me in the ass again. When I was loading animations I assumed the hotspot would be the same for each frame and I even left a comment, something like "If the hotspot varies from frame to frame then you're on your own." Then I actually saw the animations and different frames were actually different sizes (e.g. one frame the sheep's head is up, the other it's down, so the first frame is taller.) Because I was just drawing every image based on its upper left corner, the sheep's body would bob up and down, instead of its head. (It was only 1 pixel so it actually looked pretty cute.) In the original engine, hotspots were used to correct for this. So I had to fix that, and I did so by positioning every animation frame within a larger "tile" in a spritesheet. So I had to calculate a large enough tile to include each frame size plus the largest possible offset for that frame.

Writing the decoder was really the fun part, after I got something working and it would appear properly in the editor and be fixed across all the levels it was a big rush. The manual work of reimplementing the game logic in Godot was much less rewarding. I got about halfway through reimplementing each of Hidden Forest, Harara Mountains and Pinewood Heights. A lot of it was just tweaking Godot particle effects or NPC behavior until they looked right (or close enough.) The hard part was getting the ball squish animation right, I modeled it as a spring between the wall the ball was contacting and a point mass at the center of the ball. So if the ball collided with a wall I would actually shrink the ball's collision object to accommodate the wall, and apply a force based on the spring, and then squish the sprite vertically or horizontally to match. It was a little janky and didn't always bounce to exactly the same height but the gameplay felt OK and it looked great. 

**Acknowledgements**

Thanks to Smidge from here: https://forums.sonicretro.org/threads/cca-and-gam-file-format-info-and-more.24592/
for documenting his own efforts to reverse-engineer the format, way back in 2011. It was a huge help!
(The original document is available on archive.org.)

**AI Content**

This repository contains no AI-written code. *All mistakes are my own.*

**License**

Released under the MIT license.
