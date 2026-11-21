from pathlib import Path
import hashlib
import sys
digest = hashlib.sha256(Path(sys.argv[1]).read_bytes()).digest()
(Path(__file__).resolve().parent/'ootrr_ap_digest.h').write_text(
    'static const unsigned char ap_dll_sha16[32] = {' + ','.join(map(str,digest)) + '};\n',
    encoding='ascii',newline='\n')
