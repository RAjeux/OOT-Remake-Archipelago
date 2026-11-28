import copy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'client'));sys.path.insert(0,str(ROOT/'tests'))
from test_access_logic import fixture
from ootrr_triforce.access_logic import AccessLogic,validate
from ootrr_triforce.room_identity import token
from ootrr_triforce.native_setup import cursor_hash
from ootrr_triforce.install_mod import build_cache

class DonorProvenanceTests(unittest.TestCase):
 def test_provenance_cannot_change_rules_and_is_room_salted(self):
  base=fixture();raw=copy.deepcopy(base);raw['constructor_donor']=dict(schema=1,mode='native_vanilla',reason='native_token_capacity')
  for held in ({},{'Bow':1},{'Hookshot':1,'Small Key (Forest Temple)':1,'Progressive Wallet':2}):
   left,right=AccessLogic(base).sweep(held),AccessLogic(raw).sweep(held)
   self.assertEqual((left.reach,left.won),(right.reach,right.won))
  self.assertNotEqual(token('RoomA',1,'same-native-checksum',access_logic=base),token('RoomA',1,'same-native-checksum',access_logic=raw))
  a=token('RoomA',1,'same-native-checksum',access_logic=raw);b=token('RoomB',1,'same-native-checksum',access_logic=raw)
  self.assertNotEqual(a,b);self.assertNotEqual(cursor_hash(a),cursor_hash(b))
  self.assertNotEqual(build_cache(ROOT/'build/private',a,'nx2navi',{},ROOT/'build/game'),build_cache(ROOT/'build/private',b,'nx2navi',{},ROOT/'build/game'))
 def test_malformed_provenance_does_not_silently_claim_a_constructor_proof(self):
  for donor in (False,{},dict(schema=True,mode='native_vanilla',reason='native_token_capacity'),dict(schema=2,mode='native_vanilla',reason='native_token_capacity'),dict(schema=1,mode='fake',reason='native_token_capacity'),dict(schema=1,mode='native_vanilla',reason='ignore_validation'),dict(schema=1,mode='native_vanilla',reason='native_token_capacity',bypass=True)):
   raw=fixture();raw['constructor_donor']=donor
   with self.subTest(donor=donor),self.assertRaises(ValueError):validate(raw)
if __name__=='__main__':unittest.main()
