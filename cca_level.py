import godot_parser
from cca_item import ActiveItem, BackdropItem, Instance
import cca_util
from cca_image import TileSet
from pathlib import Path
import re

class TileMap:

    def __init__( self, tileSet ):
        self.tileSet = tileSet
        self.tiles = {}

    def maybeAddTiles( self, instance ):
        tileSize = self.tileSet.tileSize
        tileConvertSize = self.tileSet.tileConvertSize
        if not instance.canBeTile( tileSize, tileConvertSize ):
            return False

        # Check if any tile which the split image would overlap already has a tile
        tileSrcPositions = self.tileSet.tileTexturePositions[ instance.item.image.id ]
        imageOrigin = ( instance.y // tileSize, instance.x // tileSize )
        for row, srcRow in enumerate( tileSrcPositions ):
            for col, tileTexturePos in enumerate( srcRow ):
                dstPos = ( imageOrigin[ 0 ] + row, imageOrigin[ 1 ] + col )
                # If the new tile is fully opaque, we can discard the old one
                opaque = self.tileSet.opaque[ tileTexturePos ]
                if dstPos in self.tiles and not opaque:
                    return False

        # If not, go ahead and place the tiles associated with this image
        for row, tileSrcPosRow in enumerate( tileSrcPositions ):
            for col, tileSrcPos in enumerate( tileSrcPosRow ):
                dstPos = ( imageOrigin[ 0 ] + row, imageOrigin[ 1 ] + col )
                self.tiles[ dstPos ] = tileSrcPos
        return True

    def writeTileMap( self, levelScene ):
        tileArray = []
        tileSize = self.tileSet.tileSize
        
        # It appears that each tile is 6 u16s
        # stored in a poolIntArray as 3 s32s :facepalm:
        def makeS32( v1, v2 ):
            val = v1 << 16 | v2
            if val & ( 1 << 31 ):
                val = -val
                val &= ( ( 1 << 31 ) -1 )
            return val

        # From godot source code, format: x, y, tile (?), flags, atlas x, atlas y
        for tilePos, atlasPos in self.tiles.items():
            tileArray.append( makeS32( tilePos[ 0 ], tilePos[ 1 ] ) )
            tileArray.append( 0 )
            tileArray.append( makeS32( atlasPos[ 0 ], atlasPos[ 1 ] ) )

        gdTileArray = godot_parser.GDObject( 'PoolIntArray', *tileArray )
        gdTransform = godot_parser.GDObject(
            'Transform2D', tileSize, 0, 0, tileSize, 0, 0 )
        
        tileMapNode = godot_parser.Node(
            self.tileSet.name(),
            type='TileMap',
            properties={
                'z_index': cca_util.TILE_Z_INDEX,
                'tile_set': self.tileSet.subResource.reference,
                'cell_size': godot_parser.Vector2( tileSize, tileSize ),
                'cell_custom_transform': gdTransform,
                'format': 1,
                'tile_data': gdTileArray,
                '__meta__': { '_edit_lock_': True }
            }
        )
        with levelScene.use_tree() as levelTree:
            levelTree.root.add_child( tileMapNode )        

class Level( cca_util.MmfObject ):
    header = b'Fram\00{8}v1.5.{8}LFrame'
    
    def __init__( self, buf, images=None, tileSize=None, tileConvertSize=None, skip=False ):
        super().__init__( buf )
        self.go( self.header )
        self.go( b'Tit' )
        self.skip( 24 )
        self.name = cca_util.safeName( self.bite( cca_util.END4 ).decode() )
        print( f"  Found level {self.name}" )
        if skip:
            return
        assert images
        self.items = self.readItems( images )
        self.instances = self.readInstances()
        if tileSize:
            self.tileSet = self.createTileSet( tileSize, tileConvertSize )
            if self.tileSet:
                self.tileMap = self.createTileMap( self.tileSet )
        else:
            self.tileSet = None
            self.tileMap = None

    def readItems( self, images ):
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
                item = BackdropItem( itemBuf, self.name, images )
                items[ item.id ] = item                
            elif headerType == ActiveItem.header:
                item = ActiveItem( itemBuf, self.name, images )
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
                instance = Instance(
                    self.buf[ self.offset : self.offset + 32 ], self.items )
                cca_util.trace( f"    Found instance {instance.id}" )
                if instance.item:
                    instances.append( instance )
                else:
                    cca_util.trace( f"      Skipping; no valid item" )
            self.skip( 32 )                
        return instances

    def createTileSet( self, tileSize, tileConvertSize ):
        tiles = set()
        for instance in self.instances:
            if instance.canBeTile( tileSize, tileConvertSize ):
                tiles.add( instance.item.image )
        if tiles:
            return TileSet( tileSize,
                            tileConvertSize,
                            tiles,
                            self.name )
        return None

    def createTileMap( self, tileSet ):
        tileMap = TileMap( tileSet )
        # Filter out instances that get added to the tileMap
        self.instances = [ i for i in self.instances if not tileMap.maybeAddTiles( i ) ]
        return tileMap
    
    def writeLevel( self, annotate ):
        levelPath = cca_util.filePath( self.name )
        Path( levelPath ).mkdir( parents=True, exist_ok=True )
        if self.items:
            itemPath = f'{levelPath}/{cca_util.ITEM_DIR}'
            Path( itemPath ).mkdir( exist_ok=True )
        levelScene = godot_parser.GDScene()
        with levelScene.use_tree() as levelTree:
            levelTree.root = godot_parser.Node( self.name, type="Node" )
            for item in self.items.values():
                if isinstance( item, ActiveItem ):
                    item.writeActiveItem( annotate )
                item.addItemResource( levelScene )
            for instance in self.instances:
                instance.addInstanceToLevel( annotate, levelTree.root )

        if self.tileSet and self.tileMap:
            self.tileSet.writeTexture()
            self.tileSet.writeTileSet( levelScene )
            self.tileMap.writeTileMap( levelScene )

        levelScene.write( f'{levelPath}/{self.name}.tscn' )

class Application( cca_util.MmfObject ):
    
    def __init__( self,
                  buf,
                  images=None,
                  tileSize=None,
                  tileConvertSize=None,
                  onlyLevel=None ):
        super().__init__( buf )
        self.go( b'LApplication' )
        self.go( b'Abou' )
        self.skip( 24 )
        self.name = cca_util.safeName( self.bite( cca_util.END4 ).decode() )
        self.skip( 16 )
        self.author = self.bite( cca_util.END4 ).decode()
        print( f"Parsing app {self.name} by {self.author}" )        
        self.levels = self.readLevels( images, tileSize, tileConvertSize, onlyLevel )

    def readLevels( self, images, tileSize, tileConvertSize, onlyLevel ):
        levels = []
        # Go to start of first Level.header
        self.seek( self.search( Level.header ) )
        while ( levelBuf := self.bite( Level.header ) ):
            if onlyLevel:
                # Parse only the title first; if it's not the one we want, skip the whole level
                tempLevel = Level( levelBuf, skip=True )
                if tempLevel.name != onlyLevel:
                    continue
            levels.append( Level( levelBuf, images, tileSize, tileConvertSize ) )
        return levels

    def writeLevels( self, annotate, levelName=None ):
        for level in self.levels:
            if levelName is None or level.name == levelName:
                level.writeLevel( annotate )
