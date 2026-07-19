#!/usr/bin/python3

import argparse
from pathlib import Path
import mmf_util
from mmf_image import readImages, writeImageFiles
from mmf_level import Level, Application

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument( "inFile", help="MMF 1.5 project file" )
    parser.add_argument( "-v", "--verbose",
                         help="include debug output",
                         action='store_true' )
    parser.add_argument( "-a", "--annotate",
                         help="include original parsed fields in Godot object description",
                         action="store_true" )
    parser.add_argument( "--transparent-color",
                         help="Hex format color for transparent background in images",
                         type=str,
                         default="000000" )
    parser.add_argument( "-t", "--tile-size",
                         type=int,
                         help="Tile size for tileMap, if not specified none is generated." )
    parser.add_argument( "-T", "--tile-convert-size",
                         type=int,
                         help="Generate tiles only for sprites which are exactly this size." )
    parser.add_argument( "-l", "--level",
                         type=str,
                         help="Only output this level and the images it uses." )
    parser.add_argument( "-ll", "--list-levels",
                         help="List levels in the application and exit.",
                         action='store_true' )
    parser.add_argument( "-i", "--images-all",
                         action='store_true',
                         help="Include all images" )
    parser.add_argument( "-o", "--out", help="output directory" )    

    args = parser.parse_args()

    mmf_util.debug = args.verbose
    annotate = args.annotate
    bgColor = int( args.transparent_color, 16 )
    transparencyColor = ( bgColor >> 16, bgColor >> 8 & 0xff, bgColor & 0xff, 255 )

    cca = open( args.inFile, 'rb' )
    
    buf = mmf_util.Buffer( cca.read() )

    tileSize = args.tile_size if args.tile_size else None
    tileConvertSize = args.tile_convert_size if args.tile_convert_size else None
    level = args.level if args.level else None    
    levelTitlesOnly = args.list_levels
    allImages = args.images_all
    mmf_util.outDir = args.out if args.out and not levelTitlesOnly else None

    if levelTitlesOnly:
        Application( buf, onlyLevel="nolevelnamewillevermatchthishyperspecificstring" )
        exit( 0 )

    AGMIs = readImages( buf, transparencyColor )
    # AGMI0 seems to be unused assets, editor icons, etc.
    # AGMI1 appears to everything contained in the game itself
    
    # Parse application
    app = Application( buf, AGMIs[ 1 ], tileSize, tileConvertSize, level )

    # Write application out, if applicable
    if args.out:
        writeImageFiles( AGMIs )
        app.writeLevels( annotate, level )
