#!/usr/bin/python3

import argparse
import copy
import godot_parser
from pathlib import Path
import pdb
from PIL import Image
import re
import sys


END4 = b'\x00\x04' # Often used as string terminator
IMAGE_DIR = 'sprites'
ITEM_DIR = 'objects'
DGTS = 4 # How many digits to include in e.g. id numbers in names

debug = False
annotate = False
binAnnotate = False
def trace( t ):
    if debug:
        print( t )

outDir = None
# Store images globally so we can give them sensible names
# once we find out which Items refer to them
images = {}

class Buffer( bytes ):

    def __new__( cls, buf ):
        return super().__new__( cls, buf )

    def __init__( self, buf, baseOffset=0 ):
        self.baseOffset = baseOffset
    
    def __getitem__( self, index ):
        ret = super().__getitem__( index )
        if isinstance( index, slice ):
            ret = Buffer( ret )
            ret.baseOffset = self.baseOffset            
            if index.start is not None:
                ret.baseOffset += index.start
        return ret

    def __repr__( self ):
        return f"@0x{self.baseOffset:x}:  {super().__repr__()}"

    def __format__( self, format_spec ):
        return f"@0x{self.baseOffset:x}:  {super().__format__( format_spec )}"

def safeName( string ):
    string = string.replace( ' ', '-' )
    string = "".join( [ c for c in string if c.isalnum() or c in [ '-', '_' ] ] )
    return string

def findOffsets( contents, pattern, start=0, end=None ):
    if end is None:
        end = len( contents )
    offsets = []
    offset = contents.find( pattern, start, end )
    while offset != -1:
        offsets.append( offset )
        offset = contents.find( pattern, offset + 4, end )
    return offsets

class MmfObject:
    
    def __init__( self, buf ):
        self.buf = buf
        self.offset = 0

    def seek( self, offset ):
        assert offset >= 0
        assert offset < len( buf )
        self.offset = offset

    def read( self, length ):
        self.offset += length
        return self.buf[ self.offset - length: self.offset ]

    def tell( self ):
        return self.offset

    def getU( self, length ):
        return int.from_bytes( self.read( length ), byteorder='little', signed=False )

    def getS( self, length ):
        return int.from_bytes( self.read( length ), byteorder='little', signed=True )

    def skip( self, length ):
        self.offset += length

    def search( self, pattern, end=None ):
        if end is None:
            end = len( self.buf )
        regex = re.compile( pattern )
        m = regex.search( self.buf, pos=self.offset, endpos=end )
        if m:
            return m.start()
        else:
            return None

    def go( self, pattern, end=None ):
        # seek to right AFTER the first match of the pattern
        self.seek( self.search( pattern ) + len( pattern ) )

    def bite( self, pattern, end=None, length=None ):
        # Get the next object in a list of objects
        # where each object's header matches "pattern."
        if end is None:
            if length:
                end = self.offset + length
            else:
                end = len( self.buf )
        regex = re.compile( pattern )
        # Ignore matches that are right at the current offset for easy repetition
        m = regex.search( self.buf, pos=self.offset + 1, endpos=end )
        if m:
            end = m.start()
        start = self.offset
        self.offset = end
        return self.buf[ start : end ]

    def doAnnotate( self, node, description="", dump=True ):
        if description:
            description = f'\n\n{description}\n'
        if dump:
            exclude = [ 'offset', 'result', 'gdResource' ]
            if not binAnnotate:
                exclude.append( 'buf' )
            garbage = [ f'{key}: {val}' for key, val in vars( self ).items() if key not in exclude ]
            description += '\n'.join( garbage )
        meta = node.get( '__meta__', {} )
        meta[ '_editor_description_' ] = \
            meta.get( '_editor_description_', "" ) + description
        node[ '__meta__' ] = meta

class AgmiHeader( MmfObject ):
    def __init__( self, buf ):
        super().__init__( buf )
        self.agmiTag = self.read( 4 )
        assert self.agmiTag == b'AGMI'
        self.unknown1 = self.getU( 4 );
        self.unknown2 = self.getU( 2 );
        self.unknown3 = self.getU( 2 );
        self.palette = [ self.getSwatch() for _ in range( 256 ) ]
        self.spriteCount = self.getU( 4 );

    def getSwatch( self ):
        b = self.getU( 1 )
        g = self.getU( 1 )
        r = self.getU( 1 )
        null = self.getU( 1 )
        assert null == 0
        return ( r, g, b, 255 )

FLAG_24BPP = 0x0404
FLAG_16BPP = 0x0206
FLAG_8_BIT_INDEX = 0x0103

class MmfImage( MmfObject ):
    def __init__( self, buf, header, agmiID, transparentColor ):
        super().__init__( buf )
        self.transparentColor = transparentColor
        self.id = self.getU( 4 )
        self.unknown = self.getU( 2 )
        self.alwaysOne = self.getU( 4 )
        self.rleLength = self.getU( 4 )
        self.width = self.getU( 2 )
        self.height = self.getU( 2 )
        self.flags = self.getU( 2 )
        assert int( self.flags ) in [ FLAG_24BPP, FLAG_16BPP, FLAG_8_BIT_INDEX ]
        self.hotspotX = self.getS( 2 )
        self.hotspotY = self.getS( 2 )
        self.actionSpotX = self.getS( 2 )
        self.actionSpotY = self.getS( 2 )
        self.result = Image.new( "RGBA", ( self.width, self.height ), color=(0, 0, 0, 0) )
        self.x = 0
        self.y = 0
        self.readImage()
        self.name = f'AGMI{agmiID}_0x{self.id:x}'
        # Now that we know how long the image is, truncate the buffer to only
        # include the binary data for this image.
        self.buf = self.buf[ :self.tell() ]

    def getPixel( self ):
        if self.flags == FLAG_24BPP:
            b = self.getU( 1 )
            g = self.getU( 1 )
            r = self.getU( 1 )
            pixel = ( r, g, b, 255 )
        elif self.flags == FLAG_16BPP:
            assert False
        elif self.flags == FLAG_8_BIT_INDEX:
            index = self.getU( 1 )
            pixel = header.palette[ index ]
        else:
            assert False
        if pixel == self.transparentColor:
            pixel = ( 0, 0, 0, 0 )
        return pixel

    def readImage( self ):

        def addPixel( pixel, count=1 ):
            for _ in range( count ):
                if self.x == self.width:
                    trace( "Skipping null terminator" )
                    self.x = 0
                    self.y += 1
                else:
                    trace( self.x, self.y, '=', pixel )
                    pixels[ self.x, self.y ] = pixel
                    self.x += 1

        pixels = []

        rleStart = self.tell()
        while ( cc := self.getU( 1 ) ) != 0x0:
            runLength = cc & 0x7F
            if cc & 0x80: # Read next n pixels
                for _ in range( runLength ):
                    pixels.append( self.getPixel() )
            else: # Copy next pixel n times
                pixels.extend( [ self.getPixel() ] * runLength )

        if self.tell() != rleStart + self.rleLength:
            print( "image length mismatch: ", f.tell(), rleStart, rleLength )

        assert ( len( pixels ) == self.width * self.height or
                 len( pixels ) == ( self.width + 1 ) * self.height )

        dataWidth = len( pixels ) // self.height

        img = self.result.load()

        for y in range( self.height ):
            for x in range( self.width ):
                img[ x, y ] = pixels[ y * dataWidth + x ]

    def resourcePath( self ):
        return f'res://{IMAGE_DIR}/{self.name}.png'

    def write( self, scene ):
        # gdResource is not object-scoped since the same image may be referred
        # in multiple scenes.
        return scene.add_ext_resource( self.resourcePath(), "Texture" )
    
class Item( MmfObject ):
    ignored = False

    def __init__( self, buf ):
        super().__init__( buf )
        self.go( b'ItNa' )
        self.skip( 24 )
        self.name = self.bite( END4 ).decode( 'cp1252', errors='replace' )
        self.seek( 0 )
        self.go( self.idKey )
        self.id = self.getU( 4 )
        self.gdResource = None        
        print( f"    Parsing {self.header.decode()} {self.name}" )
    
class BackdropItem( Item ):
    header = b'LBackdropItem'
    idKey = b'SBOs'

    def __init__( self, buf ):
        super().__init__( buf )

        # Get the image ID
        self.seek( 0 )
        self.go( b'icnI' )
        self.skip( 4 )
        self.imageId = self.getU( 4 )
        image = images[ self.imageId ]
        # Update the image name to something more human-readable (hopefully)
        # Include the original ID to avoid cross-level name collisions
        image.name = f'{self.name}-0x{image.id:x}'
        self.origin = ( image.hotspotX, image.hotspotY )
        print( f"{image.name} origin: {self.origin}" )

    def write( self, levelScene ):
        # Since backdrops are static images, just add an external resource
        self.gdResource = images[ self.imageId ].write( levelScene )

class ActiveItem( Item ):
    header = b'LActiveItem'
    idKey = b'LFFs'

    def __init__( self, buf ):
        super().__init__( buf )
        self.animations = self.loadAnimations()

    def loadAnimations( self ):
        # Animation format:
        # one AnSt: n Anix (actions?)
        # each Anix: n Dirx (directions?)
        # each Dirx: n Imag (images)
        # each Imag: just an image ID
        # Each AnSt, Anix, and Dirx has the number of elements it contains.
        
        animations = []

        self.go( b'AnSt' )
        anixCount = self.getU( 4 )
        for anixId in range( anixCount ):
            directions = []
            animations.append( directions )
            self.go( b'Anix' )
            dirxCount = self.getU( 4 )
            trace( f"      Anix dirxCount {dirxCount}" )
            for dirxId in range( dirxCount ):
                frames = []
                directions.append( frames )
                self.go( b'Dirx' )
                imagCount = self.getU( 4 )
                trace( f"        Dirx imagCount {imagCount}" )
                for frameId in range( imagCount ):
                    self.go( b'Imag' )
                    imageId = self.getU( 4 )
                    image = images[ imageId ]
                    image.name = \
                        f'{self.name}_{anixId:0{DGTS}}_{dirxId:0{DGTS}}_{frameId:0{DGTS}}-0x{image.id:x}'
                    frames.append( imageId )
                    trace( f"          Imag {frames[-1]:x} origin ({image.actionSpotX}, {image.actionSpotY})" )

        # I guess technically the hotspot can vary between frames in an animation
        # if it does you're on your own.
        self.origin = ( image.hotspotX, image.hotspotY )
        return animations

    def write( self, levelScene ):
        # ActiveItems can have lots of animation frames, so give them their own scene
        gdItemScene = godot_parser.GDScene()
        gdAnimations = []
        
        for mmfAnimId, mmfAnimation in enumerate( self.animations ):
            for mmfDirId, mmfDirection in enumerate( mmfAnimation ):
                frameRefs = []
                for imageId in mmfDirection:
                    frameResource = images[ imageId ].write( gdItemScene )
                    frameRefs.append( frameResource.reference )
                gdAnimations.append( {
                    'loop': True,
                    'name': f'anix{mmfAnimId:0{DGTS}}_{mmfDirId:0{DGTS}}',
                    'speed': 5.0,
                    'frames': frameRefs
                } )
                
        gdFrames = gdItemScene.add_sub_resource( "SpriteFrames" )
        gdFrames[ "animations" ] = gdAnimations
        
        with gdItemScene.use_tree() as itemTree:
            itemTree.root = godot_parser.Node( self.name, type="Area2D" )
            # All subnodes of this node are treated as a group
            itemTree.root[ '__meta__' ] = { '"_edit_group_"': True }
            node = godot_parser.Node(
                f'{self.name}Sprites',
                type='AnimatedSprite',
                properties={
                    'frames': gdFrames.reference,
                    'animation': gdAnimations[ 0 ][ 'name' ],
                    'offset': godot_parser.Vector2(
                        -1 * self.origin[ 0 ], -1 * self.origin[ 1 ] ),
                    'centered': False
                }
            )
            if annotate:
                self.doAnnotate( node )
            itemTree.root.add_child( node )
        path = f'{ITEM_DIR}/{self.name}-{self.id}.tscn'
        gdItemScene.write( f'./{outDir}/{path}' )
        self.gdResource = levelScene.add_ext_resource( f'res://{path}', 'PackedScene' )
    
class Instance( MmfObject ):

    def __init__( self, buf ):
        super().__init__( buf )
        assert self.read( 4 ) == b'Inst'
        self.x = self.getU( 4 )
        self.y = self.getU( 4 )
        self.id = self.getU( 4 )
        self.unknown1 = self.getU( 4 )
        self.unknown2 = self.getU( 4 )
        self.itemId = self.getU( 4 )
        # Also observed last element as e.g. 0
        # assert self.getU( 4 ) == 0xFFFFFFFF

    def write( self, items, levelRoot ):
        item = items.get( self.itemId, None )
        if not item:
            return
        gdPosition = godot_parser.Vector2( self.x, self.y )
        if type( item ) == ActiveItem:
            node = godot_parser.Node(
                f'{item.name}_{self.id}',
                type='Area2D',
                instance=item.gdResource.id,
                properties={ 'position': gdPosition }
            )
            if annotate:
                self.doAnnotate( node )
        elif type( item ) == BackdropItem:
            offset = godot_parser.Vector2( -1 * item.origin[ 0 ], -1 * item.origin[ 1 ] )
            node =godot_parser.Node(
                f'{item.name}_{self.id}',
                type='Sprite',
                properties={
                    'texture': item.gdResource.reference,
                    'position': gdPosition,
                    'centered': False,
                    'offset': offset
                }
            )
            if annotate:
                self.doAnnotate( node )
                # backdropItems are just an external resource, so annotations
                # for the image and item need to be attached to the instance
                item.doAnnotate( node, description="   ***ITEM:***   " )
                images[ item.imageId ].doAnnotate( node, description="   ***IMAGE:***   " )
        else:
            assert False
                
        levelRoot.add_child( node )

class MmfLevel( MmfObject ):
    header = b'Fram\00{8}v1.5.{8}LFrame'
    
    def __init__( self, buf ):
        super().__init__( buf )
        self.go( self.header )
        self.go( b'Tit' )
        self.skip( 24 )
        self.name = safeName( self.bite( END4 ).decode( 'cp1252', errors='replace') )
        print( f"  Parsing level {self.name}" )        
        self.items = self.readItems()
        self.instances = self.readInstances()

    def readItems( self ):
        items = {}
        self.seek( 0 )
        self.go( b'class cHandleItemList<class LFrameItem>' )
        expectedItems = self.getU( 4 )
        itemHeaderRegex = b'v1\\.5.{8}(L\\w{4,12}Item)'
        
        # Go to start of first itemHeader
        self.seek( self.search( itemHeaderRegex ) )
        while ( itemBuf := self.bite( itemHeaderRegex ) ):
            headerType = re.match( itemHeaderRegex, itemBuf ).group( 1 )
            if headerType == BackdropItem.header:
                item = BackdropItem( itemBuf )
                items[ item.id ] = item                
            elif headerType == ActiveItem.header:
                item = ActiveItem( itemBuf )
                items[ item.id ] = item                
            else:
                print( f"***WARNING:*** Skipping item of type {headerType}" )
        if len( items ) != expectedItems:
            print( "***WARNING:*** Did not get the expected number of items." )
        return items

    def readInstances( self ):
        instances = []
        self.seek( 0 )
        self.go( b'class cHandleItemList<class LFrameItemInstance>' )
        instanceCount = self.getU( 4 )
        for _ in range( instanceCount ):
            # Instance list can also contain e.g. IPIn ?            
            if self.buf[ self.offset : self.offset + 4 ] == b'Inst':
                instance = Instance( self.buf[ self.offset : self.offset + 32 ] )
                trace( f"    Found instance {instance.id}" )
                instances.append( instance )
                self.skip( 32 )
        instances.reverse()
        return instances

    def write( self, gameScene, gameRoot ):
        levelScene = godot_parser.GDScene()
        with levelScene.use_tree() as levelTree:
            levelTree.root = godot_parser.Node( self.name, type="Node" )
            for item in self.items.values():
                item.write( levelScene )
            for instance in self.instances:
                instance.write( self.items, levelTree.root )
        path = f'{self.name}.tscn'
        levelScene.write( f'./{outDir}/{path}' )
        gdResource = gameScene.add_ext_resource( f'res://{path}', 'PackedScene' )
        gameRoot.add_child(
            godot_parser.Node( self.name, type="Node",instance=gdResource.id ) )

class MmfApplication( MmfObject ):
    
    def __init__( self, buf ):
        super().__init__( buf )
        self.go( b'LApplication' )
        self.go( b'Abou' )
        self.skip( 24 )
        self.name = safeName( self.bite( END4 ).decode( 'cp1252', errors='replace' ) )
        self.skip( 16 )
        self.author = self.bite( END4 ).decode( 'cp1252', errors='replace' )
        print( f"Parsing app {self.name} by {self.author}" )        
        self.levels = self.readLevels()

    def readLevels( self ):
        levels = []
        # Go to start of first MmfLevel.header
        self.seek( self.search( MmfLevel.header ) )
        while ( levelBuf := self.bite( MmfLevel.header ) ):
            levels.append( MmfLevel( levelBuf ) )
        return levels

    def write( self ):
        gameScene = godot_parser.GDScene()
        with gameScene.use_tree() as tree:
            tree.root = godot_parser.Node( self.name, type="Node" )
            self.doAnnotate(
                tree.root,
                description=f"Original project author: {self.author}",
                dump=False
            )
            for level in self.levels:
                level.write( gameScene, tree.root )
        gameScene.write( f'./{outDir}/{self.name}.tscn' )

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument( "inFile", help="MMF 1.5 project file" )
    parser.add_argument( "-o", "--outDir", help="output directory" )
    parser.add_argument( "-v", "--verbose",
                         help="include debug output",
                         action='store_true' )
    parser.add_argument( "-a", "--annotate",
                         help="include original parsed fields in Godot object description",
                         action="store_true" )
    parser.add_argument( "-b", "--binaryAnnotate",
                         help="include original binary in Godot object description",
                         action="store_true" )
    parser.add_argument( "--transparentColor",
                         help="Hex format color for transparent background in images",
                         type=str,
                         default="000000" )
    args = parser.parse_args()

    debug = args.verbose
    annotate = args.annotate
    binAnnotate = args.binaryAnnotate
    bgColor = int( args.transparentColor, 16 )
    transparencyColor = ( bgColor >> 16, bgColor >> 8 & 0xff, bgColor & 0xff, 255 )

    cca = open( args.inFile, 'rb' )
    
    buf = Buffer( cca.read() )
    AGMIOffsets = findOffsets( buf, b'AGMI' )
    print( f"Found AGMIs: { [ f"{AGMI:x}" for AGMI in AGMIOffsets ] }" )

    AGMIs = []
    
    for agmiID, agmiOffset in enumerate( AGMIOffsets ):
        AGMIs.append( {} ) # Keyed by ID
        agmiBuf = buf[ agmiOffset: ]
        header = AgmiHeader( agmiBuf )
        agmiBuf = agmiBuf[ header.tell(): ]
        for imageCnt in range( header.spriteCount ):
            # Note: We don't know how long an image is until we parse it.
            # So just slice off each image from the start of the buffer as we find them.
            image = MmfImage( agmiBuf, header, agmiID, transparencyColor )
            print( f'  found image: {image.width}x{image.height} {image.name} at 0x{agmiBuf.baseOffset:x}' )
            AGMIs[ agmiID ][ image.id ] = image
            agmiBuf = agmiBuf[ image.tell(): ]

    # AGMI0 appears to be unused/editor UI images
    # AGMI1 appears to be the images actually used in the game
    images = AGMIs[ 1 ]
            
    # Parse application
    app = MmfApplication( buf )
            
    # If outdir is specified, dump everything
    if args.outDir:
        outDir = args.outDir
        
        print( f"Saving data to {outDir}" )
        Path( f"./{outDir}" ).mkdir( exist_ok=True )
        if any( AGMIs ):
            imagesPath = f"./{outDir}/{IMAGE_DIR}"
            Path( imagesPath ).mkdir( exist_ok=True )
            for AGMI in AGMIs:
                for image in AGMI.values():
                    image.result.save( f'{imagesPath}/{image.name}.png' )
        if any( l.items for l in app.levels ):
            Path( f"./{outDir}/{ITEM_DIR}" ).mkdir( exist_ok=True )
        app.write()
