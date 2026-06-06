import godot_parser
import mmf_util
from PIL import Image
from pathlib import Path
from math import ceil

import pdb

class AgmiHeader( mmf_util.MmfObject ):
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

class MmfImage( mmf_util.MmfObject ):
    FLAG_24BPP = 0x0404
    FLAG_16BPP = 0x0206
    FLAG_8_BIT_INDEX = 0x0103
    
    def __init__( self, buf, header, agmiID, transparentColor ):
        super().__init__( buf )
        self.header = header
        self.transparentColor = transparentColor
        self.id = self.getU( 4 )
        self.unknown = self.getU( 2 )
        self.alwaysOne = self.getU( 4 )
        self.rleLength = self.getU( 4 )
        self.width = self.getU( 2 )
        self.height = self.getU( 2 )
        self.flags = self.getU( 2 )
        assert int( self.flags ) in [ self.FLAG_24BPP, self.FLAG_16BPP, self.FLAG_8_BIT_INDEX ]
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
        # Set to False if included in an atlas
        self.writePng = True

    def getPixel( self ):
        if self.flags == self.FLAG_24BPP:
            b = self.getU( 1 )
            g = self.getU( 1 )
            r = self.getU( 1 )
            pixel = ( r, g, b, 255 )
        elif self.flags == self.FLAG_16BPP:
            assert False
        elif self.flags == self.FLAG_8_BIT_INDEX:
            index = self.getU( 1 )
            pixel = self.header.palette[ index ]
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
        return f'res://{mmf_util.IMAGE_DIR}/{self.name}.png'

    def writeImage( self, outDir, annotate, scene ):
        # gdResource is not object-scoped since the same image may be referred
        # in multiple scenes.
        return scene.add_ext_resource( self.resourcePath(), "Texture" )

def readImages( buf, transparencyColor ):
    AGMIOffsets = mmf_util.findOffsets( buf, b'AGMI' )
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
    return AGMIs

def writeImageFiles( outDir, AGMIs ):
    if any( AGMIs ):
        imagesPath = f"./{outDir}/{mmf_util.IMAGE_DIR}"
        Path( imagesPath ).mkdir( parents=True, exist_ok=True )
        for AGMI in AGMIs:
            for image in AGMI.values():
                if image.writePng:
                    image.result.save( f'{imagesPath}/{image.name}.png' )

class Atlas:

    def __init__( self, spriteSize, images, name ):
        self.name = name
        self.spriteSize = spriteSize
        self.sprites = {} # imageId : position in atlas
        self.width = ceil( len( images ) ** 0.5 ) # in sprites
        textureSize = self.width * spriteSize
        if textureSize > 2048:
            print( f"***WARNING***: Atlas size {textureSize} > 2048" )
        offset = 0
        self.texture = Image.new( "RGBA", ( textureSize, textureSize ), color=(0, 0, 0, 0) )
        for image in images:
            assert image.width == image.height == spriteSize
            assert offset < self.width * self.width
            xPos = offset % self.width
            yPos = offset // self.width
            offset += 1
            self.texture.paste( image.result, ( xPos * spriteSize, yPos * spriteSize ) )
            self.sprites[ image.id ] = ( xPos, yPos )
        self.textureResource = None
        self.subResource = None

    def texturePath( self ):
        return f"{mmf_util.IMAGE_DIR}/{self.name}.png"
    
    def writeTexture( self, outDir ):
        self.texture.save( f'./{outDir}/{self.texturePath()}' )

    def writeTileSet( self, levelScene ):
        self.textureResource = \
            levelScene.add_ext_resource( f'res://{self.texturePath()}', 'Texture' )
        self.subResource = levelScene.add_sub_resource( "TileSet" )
        self.subResource[ "0/name" ] = f"{self.name}_0"
        self.subResource[ "0/texture" ] = self.textureResource.reference
        self.subResource[ "0/region" ] = \
            godot_parser.GDObject( "Rect2", 0, 0, self.texture.width, self.texture.height )
        self.subResource[ "0/tile_mode" ] = 2
        self.subResource[ "0/autotile/tile_size" ] = \
            godot_parser.Vector2( self.spriteSize, self.spriteSize )
        self.subResource[ "0/z_index" ] = -1
        
