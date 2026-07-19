import re
import pdb

END4 = b'\x00\x04' # Often used as string terminator
_4END = b'\x04\x00' # Sometimes it's reversed?
IMAGE_UNUSED_DIR = 'extraSprites'
IMAGE_COMMON_DIR = 'commonSprites'
IMAGE_SUBDIR = 'sprites'
IMAGE_WARN_SIZE = 2048
ITEM_DIR = 'objects'
DGTS = 4 # How many digits to include in e.g. id numbers in names

BACKGROUND_Z_INDEX = -300
BACKDROP_Z_INDEX = -200
TILE_Z_INDEX = -100
ACTIVE_Z_INDEX = 0

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

def filePath( path ):
    return f'./{outDir}/{path}'

def resourcePath( path ):
    return f'res://{path}'

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

    def decode( self ):
        return super().decode( 'cp1252', errors='replace' )
    
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
        self.name = ""
        self.id = -1

    def seek( self, offset ):
        assert offset >= 0
        assert offset < len( self.buf )
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

    def bite( self, pattern, patternIs='start', end=None, length=None ):
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
            if patternIs == 'start': # Pattern marks the start, cut before it
                end = m.start()
            else: # Pattern marks the end, cut after it
                end = m.end()
        start = self.offset
        self.offset = end
        return self.buf[ start : end ]

    def doAnnotate( self, node, description="", dump=True ):
        if description:
            description = f'\n\n{description}\n'
        description += f"{self.name} id {self.id} @{self.buf.baseOffset:x} {type( self ).__name__}\n"
        if dump:
            exclude = [ 'offset', 'result', 'gdResource', 'buf', 'name' ]
            garbage = [ f'{key}: {val}' for key, val in vars( self ).items() if key not in exclude ]
            description += '\n'.join( garbage )
        meta = node.get( '__meta__', {} )
        meta[ '_editor_description_' ] = \
            meta.get( '_editor_description_', "" ) + description
        node[ '__meta__' ] = meta
