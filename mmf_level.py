import godot_parser
from mmf_item import ActiveItem, BackdropItem, Instance
from mmf_util import MmfObject, safeName, END4, trace
import re

class Level( MmfObject ):
    header = b'Fram\00{8}v1.5.{8}LFrame'
    
    def __init__( self, buf, images ):
        super().__init__( buf )
        self.go( self.header )
        self.go( b'Tit' )
        self.skip( 24 )
        self.name = safeName( self.bite( END4 ).decode() )
        print( f"  Parsing level {self.name}" )        
        self.items = self.readItems( images )
        self.instances = self.readInstances()

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
                item = BackdropItem( itemBuf, images )
                items[ item.id ] = item                
            elif headerType == ActiveItem.header:
                item = ActiveItem( itemBuf, images )
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

    def writeLevel( self, outDir, annotate, gameScene ):
        levelScene = godot_parser.GDScene()
        with levelScene.use_tree() as levelTree:
            levelTree.root = godot_parser.Node( self.name, type="Node" )
            for item in self.items.values():
                item.writeItem( outDir, annotate, levelScene )
            for instance in self.instances:
                instance.writeInstance( outDir, annotate, levelTree.root, self.items )
        path = f'{self.name}.tscn'
        levelScene.write( f'./{outDir}/{path}' )
        gdResource = gameScene.add_ext_resource( f'res://{path}', 'PackedScene' )
        with gameScene.use_tree() as gameTree:
            gameTree.root.add_child(
                godot_parser.Node( self.name, type="Node",instance=gdResource.id ) )

class Application( MmfObject ):
    
    def __init__( self, buf, images ):
        super().__init__( buf )
        self.go( b'LApplication' )
        self.go( b'Abou' )
        self.skip( 24 )
        self.name = safeName( self.bite( END4 ).decode() )
        self.skip( 16 )
        self.author = self.bite( END4 ).decode()
        print( f"Parsing app {self.name} by {self.author}" )        
        self.levels = self.readLevels( images )

    def readLevels( self, images ):
        levels = []
        # Go to start of first Level.header
        self.seek( self.search( Level.header ) )
        while ( levelBuf := self.bite( Level.header ) ):
            levels.append( Level( levelBuf, images ) )
        return levels

    def writeApp( self, outDir, annotate ):
        gameScene = godot_parser.GDScene()
        with gameScene.use_tree() as tree:
            tree.root = godot_parser.Node( self.name, type="Node" )
            self.doAnnotate(
                tree.root,
                description=f"Original project author: {self.author}",
                dump=False
            )
        for level in self.levels:
            level.writeLevel( outDir, annotate, gameScene )
        gameScene.write( f'./{outDir}/{self.name}.tscn' )
