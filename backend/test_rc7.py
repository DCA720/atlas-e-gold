import unittest
from unittest.mock import patch, MagicMock
import pg_signals

class RC7Tests(unittest.TestCase):
 def setUp(self):
  self.r={'signal_time_utc':'2026-11-11T18:00:00+00:00','asset':'USD',
          'horizon':'1d','score':14,'coverage':100,'window_end':'2026-11-09',
          'model_version':'3.0-rc7-experimental'}
 def test_schema_mapping(self):
  row=pg_signals._row(self.r)
  self.assertEqual(row[:3],('USD',1,14))
  self.assertEqual(row[-1].tzinfo.utcoffset(None).total_seconds(),0)
 def test_invalid_horizon(self):
  with self.assertRaises(ValueError):pg_signals._row({**self.r,'horizon':'7d'})
 def test_timezone_required(self):
  with self.assertRaises(ValueError):pg_signals._row({**self.r,'signal_time_utc':'2026-11-11T18:00:00'})
 def test_merge_idempotent_and_earliest(self):
  later={**self.r,'signal_time_utc':'2026-11-11T19:00:00+00:00'}
  rows=pg_signals.merge([later,self.r],[later])
  self.assertEqual(len(rows),1)
  self.assertEqual(rows[0]['signal_time_utc'],self.r['signal_time_utc'])
 def test_missing_db_does_not_write(self):
  with patch.dict('os.environ',{},clear=True):
   self.assertEqual(pg_signals.push([self.r]),0)
   self.assertEqual(pg_signals.pull(),[])
 def test_no_plaintext_secrets_in_status(self):
  import app
  self.assertNotIn('DATABASE_URL',app.pg_status)
if __name__=='__main__':unittest.main()
