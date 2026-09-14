"""Legacy experiment geometry defaults, shared by input adapters and recipes."""
QEC_LAYOUTS = frozenset({"surface_qec_ghz2", "surface_qec_ghz4"})

def aod_shape(value):
    """Explicit 2D shape, legacy 1xN, or the surface preset's 6x6 default."""
    if 'aod_rows' in value:
        return value['aod_rows'],value['aod_columns']
    if 'aod_traps' in value:
        if value['layout'] in QEC_LAYOUTS and value['aod_traps']==98:
            return 7,14
        return 1,value['aod_traps']
    if value['layout'] in QEC_LAYOUTS:return 7,14
    return (6,6) if value['layout']=='surface_patches' else (1,1)


def aod_offsets(value, rows, columns):
    spacing=5 if rows*columns==1 else 10
    def axis(key,count):
        if key in value:return tuple(value[key])
        if value['layout'] in QEC_LAYOUTS:
            if key=='aod_row_offsets_um' and count==7:return tuple(range(0,35,5))
            if key=='aod_column_offsets_um' and count==14:return tuple(range(0,35,5))+tuple(range(40,75,5))
        if value['layout']=='surface_patches' and count==6:return (0,10,20,40,50,60)
        return tuple(i*spacing for i in range(count))
    return axis('aod_row_offsets_um',rows),axis('aod_column_offsets_um',columns)
