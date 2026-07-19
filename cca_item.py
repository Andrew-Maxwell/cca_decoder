import godot_parser
import cca_image
import cca_util

import pdb
from PIL import Image

class ItemTag( cca_util.MmfObject ):

    def __init__( self, buf ):
        super().__init__( buf )

        self.name = self.read( 4 ).decode()
        self.unknown1 = self.getU( 4 )
        self.elements = self.getU( 4 )
        self.format = self.getU( 2 )
        self.c = self.getU( 1 )
        self.d = self.getU( 1 )
        self.contents = self.parseContents( self.buf[ self.tell(): ] )

    def parseContents( self, buf ):
        contents = []
        # Initial 2 words always appear
        if self.format == 0xD: # Colors; background and tint?
            for _ in range( 2 ):
                contents.append( (
                    self.getU( 1 ),
                    self.getU( 1 ),
                    self.getU( 1 ),
                    255 ) )
                self.skip( 1 )
        else:
            contents.append( ( self.getU( 4 ), self.getU( 4 ) ) )

        # Sometimes there is some additional content
        for _ in range( self.elements - 1 ):
            if self.format == 0x1: # Flags?
                contents.append( (
                    self.getU( 1 ),
                    self.getU( 1 ),
                    self.getU( 1 ),
                    self.getU( 1 ),
                    self.getU( 4 ),
                    self.getU( 4 ) ) )
            elif self.format == 0x4: # String
                length = self.getU( 4 )
                contents.append( self.read( length ).decode() )
            elif self.format in [ 0xa, 0xb, 0x19 ]: # ???
                pass
            else:
                cca_util.trace( f"      item tag {self.name} "
                                f"@0x{self.buf.baseOffset:x} "
                                f"unknown format {self.format:x}" )
                return []
        return contents

    def __repr__( self ):
        if self.format == 0x4:
            return str( self.contents )
        else:
            ret = ""
            for line in self.contents:
                ret += str( [ f"0x{val:x}" for val in line ] )
                ret += ','
            return ret

class Item( cca_util.MmfObject ):
    ignored = False

    def __init__( self, buf, levelName ):
        super().__init__( buf )
        assert self.read( 4 ) == b'v1.5'
        tagCount = self.getU( 4 )
        class2Len = self.getU( 4 )
        self.class2 = self.read( class2Len ).decode()
        print( f"    Found {self.class2} @0x{self.buf.baseOffset:x}", end="" )
        cca_util.trace( "" )
        self.tags = {}
        delimiter = cca_util._4END + b'[a-zA-Z]{4}'
        for _ in range( tagCount ):
            tagBuf = self.bite( delimiter, patternIs='start' )[ 2: ]
            tag = ItemTag( tagBuf )
            self.tags[ tag.name ] = tag

        self.name = self.getName()
        self.go( self.idKey )
        self.id = self.getU( 4 )
        print( f"      name {self.name} id {self.id}" )
        self.gdResource = None
        self.levelName = levelName

    def getName( self ):
        try:
            return cca_util.safeName( self.tags[ 'ItNa' ].contents[ 1 ] )
        except Exception as e:
            print( e )
            return "Unnamed"
        
    def visible( self ):
        if 'Visi' in self.tags:
            flag = self.tags[ 'Visi' ].contents[ 0 ][ 1 ] 
            assert flag in [ 0x1, 0x2 ]
            return flag == 0x2
        return True

    def opacity( self ):
        if 'InkF' in self.tags:
            value = self.tags[ 'InkF'].contents[ 2 ][ 5 ]
            assert value <= 0x80
            return ( 0x80 - value ) / 0x80
        return 1

class BackdropItem( Item ):
    header = b'LBackdropItem'
    idKey = b'SBOs'

    def __init__( self, buf, levelName, images ):
        super().__init__( buf, levelName )

        # Get the image ID
        self.seek( 0 )
        self.go( b'icnI' )
        self.skip( 4 )
        self.image = images[ self.getU( 4 ) ]
        # Update the image name to something more human-readable (hopefully)
        # Include the original ID to avoid cross-level name collisions
        self.image.name = f'{self.name}-0x{self.image.id:x}'
        self.image.levels.add( self.levelName )

    def addItemResource( self, levelScene ):
        self.gdResource = self.image.addImageResource( levelScene )

class ActiveItem( Item ):
    header = b'LActiveItem'
    idKey = b'LFFs'

    def __init__( self, buf, levelName, images ):
        super().__init__( buf, levelName )
        self.animations = self.loadAnimations( images )
        self.spriteSize, self.texture = self.generateSpriteSheet( self.animations )

    def loadAnimations( self, images ):
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
            cca_util.trace( f"      Anix dirxCount {dirxCount}" )
            for dirxId in range( dirxCount ):
                frames = []
                directions.append( frames )
                self.go( b'Dirx' )
                imagCount = self.getU( 4 )
                cca_util.trace( f"        Dirx imagCount {imagCount}" )
                for frameId in range( imagCount ):
                    self.go( b'Imag' )
                    image = images[ self.getU( 4 ) ]
                    image.name = ( f"{self.name}_"
                        f"{anixId:0{cca_util.DGTS}}_"
                        f"{dirxId:0{cca_util.DGTS}}_"
                        f"{frameId:0{cca_util.DGTS}}-0x{image.id:x}" )
                    image.levels.add( self.levelName )
                    frames.append( image )
        return animations

    def generateSpriteSheet( self, animations ):
        # Determine size of each tile in the spritesheet
        # Some sprites may be smaller than others and use the hotspot to compensate
        minHotspotX = minHotspotY = float( 'inf' )
        # Maximum of hotspot + image size
        maxExtentX = maxExtentY = 0
        maxFrames = 0
        sequenceCount = 0
        for anix in animations:
            for dirx in anix:
                sequenceCount += 1
                maxFrames = max( maxFrames, len( dirx ) )
                for image in dirx:
                    minHotspotX = min( minHotspotX, image.hotspotX )
                    minHotspotY = min( minHotspotY, image.hotspotY )
                    maxExtentX = max( maxExtentX, image.hotspotX + image.width )
                    maxExtentY = max( maxExtentY, image.hotspotY + image.height )
        # (x, y) since these are PIL image coordinates, not Godot
        self.origin = ( minHotspotX, minHotspotY )
        spriteSize = ( maxExtentX - minHotspotX, maxExtentY - minHotspotY )
        texSize = ( spriteSize[ 0 ] * maxFrames, spriteSize[ 1 ] * sequenceCount )
        if ( texSize[ 0 ] > cca_util.IMAGE_WARN_SIZE or
             texSize[ 1 ] > cca_util.IMAGE_WARN_SIZE ):
            printf( f'***WARNING***: item {self.name} spritesheet size {texSize} > '
                    f'{cca_util.IMAGE_WARN_SIZE}' )
        
        texture = Image.new( "RGBA", texSize, color=( 0, 0, 0, 0 ) )

        sequenceId = 0
        for anix in animations:
            for dirx in anix:
                for frameId, frame in enumerate( dirx ):
                    tilePos = ( frameId * spriteSize[ 0 ],
                                sequenceId * spriteSize[ 1 ] )
                    offset = ( frame.hotspotX - self.origin[ 0 ],
                               frame.hotspotY - self.origin[ 1 ] )
                    dst = ( tilePos[ 0 ] + offset[ 0 ], tilePos[ 1 ] + offset[ 1 ] )
                    texture.paste( frame.result, dst )
                sequenceId += 1
        return spriteSize, texture
                    
    def texturePath( self ):
        return f'{self.levelName}/{cca_util.IMAGE_SUBDIR}/{self.name}.png'        
    
    def path( self ):
        return  f'{self.levelName}/{cca_util.ITEM_DIR}/{self.name}-{self.id}.tscn'

    def writeTexture( self ):
        self.texture.save( cca_util.filePath( self.texturePath() ) )        
        
    def writeActiveItem( self, annotate ):
        # ActiveItems can have lots of animation frames, so give them their own scene
        gdItemScene = godot_parser.GDScene()
        gdAnimations = []

        textureResource = gdItemScene.add_ext_resource(
            cca_util.resourcePath( self.texturePath() ), 'Texture' )

        sequence = 0
        for ccaAnimId, ccaAnimation in enumerate( self.animations ):
            for ccaDirId, ccaDirection in enumerate( ccaAnimation ):
                frameRefs = []
                for frameId, _ in enumerate( ccaDirection ):
                    frame = gdItemScene.add_sub_resource( "AtlasTexture" )
                    frame[ 'flags' ] = 4 # magic number???
                    frame[ 'atlas' ] = textureResource.reference
                    frame[ 'region' ] = godot_parser.GDObject(
                        "Rect2",
                        frameId * self.spriteSize[ 0 ],
                        sequence * self.spriteSize[ 1 ],
                        self.spriteSize[ 0 ],
                        self.spriteSize[ 1 ] )
                    frameRefs.append( frame.reference )
                gdAnimations.append( {
                    'loop': True,
                    'name': ( f'anix{ccaAnimId:0{cca_util.DGTS}}_'
                              f'{ccaDirId:0{cca_util.DGTS}}' ),
                    'speed': 5.0,
                    'frames': frameRefs,
                } )
                sequence += 1
                
        gdFrames = gdItemScene.add_sub_resource( "SpriteFrames" )
        gdFrames[ "animations" ] = gdAnimations
        
        with gdItemScene.use_tree() as itemTree:
            itemTree.root = godot_parser.Node( self.name, type="Node2D" )
            # All subnodes of this node are treated as a group
            itemTree.root[ '__meta__' ] = { '"_edit_group_"': True }
            nodeProperties={
                'frames': gdFrames.reference,
                'animation': gdAnimations[ 0 ][ 'name' ],
                'centered': False
            }
            if self.origin[ 0 ] or self.origin[ 1 ]:
                nodeProperties[ 'offset' ] = \
                    godot_parser.Vector2( -1 * self.origin[ 0 ], -1 * self.origin[ 1 ] )
            if not self.visible():
                nodeProperties[ 'visible' ] = False
            if self.opacity() != 1:
                nodeProperties[ 'self_modulate' ] = \
                    godot_parser.Color( 1, 1, 1, self.opacity() )

            node = godot_parser.Node( f'{self.name}Sprites',
                                      type='AnimatedSprite',
                                      properties=nodeProperties )
            if annotate:
                self.doAnnotate( node )
                # Include annotations for all animation frames
                # because where else would we put it?
                for anix in self.animations:
                    for dirx in anix:
                        for image in dirx:
                            image.doAnnotate( node )
            itemTree.root.add_child( node )
        gdItemScene.write( cca_util.filePath( self.path() ) )

    def addItemResource( self, levelScene ):
        self.gdResource = levelScene.add_ext_resource(
            cca_util.resourcePath( self.path() ), 'PackedScene' )
    
class Instance( cca_util.MmfObject ):

    def __init__( self, buf, items ):
        super().__init__( buf )
        assert self.read( 4 ) == b'Inst'
        self.x = self.getS( 4 )
        self.y = self.getS( 4 )
        self.id = self.getU( 4 )
        self.unknown1 = self.getU( 4 )
        self.unknown2 = self.getU( 4 )
        self.item = items.get( self.getU( 4 ), None )
        if type( self.item ) == BackdropItem:
            self.zIndex = cca_util.BACKDROP_Z_INDEX
        else:
            self.zIndex = cca_util.ACTIVE_Z_INDEX
        # Also observed last element as e.g. 0
        # assert self.getU( 4 ) == 0xFFFFFFFF

    def canBeTile( self, tileSize, tileConvertSize=None ):
        if type( self.item ) != BackdropItem:
            return False
        if tileConvertSize:
            if ( self.item.image.height != tileConvertSize or
                 self.item.image.height != tileConvertSize ):
                return False
        return ( self.x % tileSize == 0 and self.y % tileSize == 0 and
                 self.item.image.width % tileSize == 0 and
                 self.item.image.height % tileSize == 0 )
        
    # NOTE: writeInstance takes a Node instead of the usual Scene
    def addInstanceToLevel( self, annotate, levelRoot ):
        if not self.item:
            return
        gdPosition = godot_parser.Vector2( self.x, self.y )
        if type( self.item ) == ActiveItem:
            node = godot_parser.Node(
                f'{self.item.name}_{self.id}',
                type='Area2D',
                instance=self.item.gdResource.id,
                properties={ 'position': gdPosition, 'z_index': self.zIndex }
            )
            if annotate:
                self.doAnnotate( node )
        elif type( self.item ) == BackdropItem:
            nodeProperties={
                'texture': self.item.gdResource.reference,
                'position': gdPosition,
                'centered': False,
                'z_index': self.zIndex,
            }
            if not self.item.visible():
                nodeProperties[ 'visible' ] = False
            if self.item.opacity() != 1:
                nodeProperties[ 'self_modulate' ] = \
                    godot_parser.Color( 1, 1, 1, self.item.opacity() )
            node = godot_parser.Node(
                f'{self.item.name}_{self.id}',
                type='Sprite',
                properties=nodeProperties
            )
            if annotate:
                self.doAnnotate( node )
                # only Nodes can have editor descriptions
                # But images/backdropItems are just an ExternalResource
                # So we need to add annotations to the instance Sprite node
                self.item.doAnnotate( node, description="***ITEM:***" )
                self.item.image.doAnnotate( node, description="***IMAGE:***" )
        else:
            assert False
                
        levelRoot.add_child( node )

