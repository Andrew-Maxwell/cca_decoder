import godot_parser
import mmf_image
import mmf_util

class Item( mmf_util.MmfObject ):
    ignored = False

    def __init__( self, buf ):
        super().__init__( buf )
        self.go( b'ItNa' )
        self.skip( 24 )
        self.name = self.bite( mmf_util.END4 ).decode( 'cp1252', errors='replace' )
        self.seek( 0 )
        self.go( self.idKey )
        self.id = self.getU( 4 )
        self.gdResource = None        
        print( f"    Parsing {self.header.decode()} {self.name} itemId {self.id}" )
    
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
            node =godot_parser.Node(
                f'{item.name}_{self.id}',
                type='Sprite',
                properties={
                    'texture': item.gdResource.reference,
                    'position': gdPosition,
                    'centered': False,
                }
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

