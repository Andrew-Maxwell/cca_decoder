import godot_parser
import mmf_image
import mmf_util

import pdb

class ItemTag( mmf_util.MmfObject ):

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
                mmf_util.trace( f"      item tag {self.name} "
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

class Item( mmf_util.MmfObject ):
    ignored = False

    def __init__( self, buf ):
        super().__init__( buf )
        assert self.read( 4 ) == b'v1.5'
        tagCount = self.getU( 4 )
        class2Len = self.getU( 4 )
        self.class2 = self.read( class2Len ).decode()
        print( f"    Found {self.class2} @0x{self.buf.baseOffset:x}", end="" )
        mmf_util.trace( "" )
        self.tags = {}
        delimiter = mmf_util._4END + b'[a-zA-Z]{4}'
        for _ in range( tagCount ):
            tagBuf = self.bite( delimiter, patternIs='start' )[ 2: ]
            tag = ItemTag( tagBuf )
            self.tags[ tag.name ] = tag

        self.name = self.getName()
        self.go( self.idKey )
        self.id = self.getU( 4 )
        print( f"      name {self.name} id {self.id}" )
        self.gdResource = None        

    def getName( self ):
        try:
            return mmf_util.safeName( self.tags[ 'ItNa' ].contents[ 1 ] )
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

    def __init__( self, buf, images ):
        super().__init__( buf )

        # Get the image ID
        self.seek( 0 )
        self.go( b'icnI' )
        self.skip( 4 )
        self.image = images[ self.getU( 4 ) ]
        # Update the image name to something more human-readable (hopefully)
        # Include the original ID to avoid cross-level name collisions
        self.image.name = f'{self.name}-0x{self.image.id:x}'

    def writeItem( self, outDir, annotate, levelScene ):
        # Since backdrops are static images, just add an external resource
        # Can't actually annotate because ext resources can't have descriptions
        self.gdResource = self.image.writeImage( outDir, annotate, levelScene )

class ActiveItem( Item ):
    header = b'LActiveItem'
    idKey = b'LFFs'

    def __init__( self, buf, images ):
        super().__init__( buf )
        self.animations = self.loadAnimations( images )

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
            mmf_util.trace( f"      Anix dirxCount {dirxCount}" )
            for dirxId in range( dirxCount ):
                frames = []
                directions.append( frames )
                self.go( b'Dirx' )
                imagCount = self.getU( 4 )
                mmf_util.trace( f"        Dirx imagCount {imagCount}" )
                for frameId in range( imagCount ):
                    self.go( b'Imag' )
                    image = images[ self.getU( 4 ) ]
                    image.name = ( f"{self.name}_"
                        f"{anixId:0{mmf_util.DGTS}}_"
                        f"{dirxId:0{mmf_util.DGTS}}_"
                        f"{frameId:0{mmf_util.DGTS}}-0x{image.id:x}" )
                    frames.append( image )

        # I guess technically the hotspot can vary between frames in an animation
        # if it does you're on your own.
        self.origin = ( image.hotspotX, image.hotspotY )
        return animations

    def writeItem( self, outDir, annotate, levelScene ):
        # ActiveItems can have lots of animation frames, so give them their own scene
        gdItemScene = godot_parser.GDScene()
        gdAnimations = []
        
        for mmfAnimId, mmfAnimation in enumerate( self.animations ):
            for mmfDirId, mmfDirection in enumerate( mmfAnimation ):
                frameRefs = []
                for image in mmfDirection:
                    frameResource = image.writeImage( outDir, annotate, gdItemScene )
                    frameRefs.append( frameResource.reference )
                gdAnimations.append( {
                    'loop': True,
                    'name': ( f'anix{mmfAnimId:0{mmf_util.DGTS}}_'
                              f'{mmfDirId:0{mmf_util.DGTS}}' ),
                    'speed': 5.0,
                    'frames': frameRefs,
                } )
                
        gdFrames = gdItemScene.add_sub_resource( "SpriteFrames" )
        gdFrames[ "animations" ] = gdAnimations
        
        with gdItemScene.use_tree() as itemTree:
            itemTree.root = godot_parser.Node( self.name, type="Area2D" )
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
        path = f'{mmf_util.ITEM_DIR}/{self.name}-{self.id}.tscn'
        gdItemScene.write( f'./{outDir}/{path}' )
        self.gdResource = levelScene.add_ext_resource( f'res://{path}', 'PackedScene' )
    
class Instance( mmf_util.MmfObject ):

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

    # NOTE: writeInstance takes a Node instead of the usual Scene
    def writeInstance( self, outDir, annotate, levelRoot, items ):
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
            nodeProperties={
                'texture': item.gdResource.reference,
                'position': gdPosition,
                'centered': False,
                'z_index': -1
            }
            if not item.visible():
                nodeProperties[ 'visible' ] = False
            if item.opacity() != 1:
                nodeProperties[ 'self_modulate' ] = \
                    godot_parser.Color( 1, 1, 1, item.opacity() )
            node =godot_parser.Node(
                f'{item.name}_{self.id}',
                type='Sprite',
                properties=nodeProperties
            )
            if annotate:
                self.doAnnotate( node )
                # only Nodes can have editor descriptions
                # But images/backdropItems are just an ExternalResource
                # So we need to add annotations to the instance Sprite node
                item.doAnnotate( node, description="***ITEM:***" )
                item.image.doAnnotate( node, description="***IMAGE:***" )
        else:
            assert False
                
        levelRoot.add_child( node )

