#!/usr/bin/python3

import argparse
from pathlib import Path
import mmf_util
from mmf_image import readImages, writeImageFiles
from mmf_level import Level, Application

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
    parser.add_argument( "--transparentColor",
                         help="Hex format color for transparent background in images",
                         type=str,
                         default="000000" )
    parser.add_argument( "-t", "--tileSize",
                         type=int,
                         help="Tile size for tileMap, if not specified none is generated." )
    args = parser.parse_args()

    mmf_util.debug = args.verbose
    annotate = args.annotate
    bgColor = int( args.transparentColor, 16 )
    transparencyColor = ( bgColor >> 16, bgColor >> 8 & 0xff, bgColor & 0xff, 255 )

    cca = open( args.inFile, 'rb' )
    
    buf = mmf_util.Buffer( cca.read() )

    AGMIs = readImages( buf, transparencyColor )
    # AGMI0 seems to be unused assets, editor icons, etc.
    # AGMI1 appears to everything contained in the game itself

    tileSize = args.tileSize if args.tileSize else None
    
    # Parse application
    app = Application( buf, AGMIs[ 1 ], tileSize )
            
    # If outdir is specified, dump everything
    if args.outDir:

        writeImageFiles( args.outDir, AGMIs )
        
        if any( l.items for l in app.levels ):
            Path( f"./{args.outDir}/{mmf_util.ITEM_DIR}" ).mkdir( exist_ok=True )
        app.writeApp( args.outDir, annotate )
