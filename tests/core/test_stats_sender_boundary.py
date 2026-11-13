"""Potentially blocking model normalization belongs to the sender."""
from core import config, offline, stats


def test_model_normalization_waits_for_sender(tmp_path,monkeypatch):
    pending,normalized,posted=[],[],[]

    class Deferred:
        def __init__(self,target,args=(),**kwargs):pending.append(lambda:target(*args))
        def start(self):pass

    monkeypatch.setattr(stats.threading,'Thread',Deferred)
    monkeypatch.setattr(offline,'is_offline',lambda:False)
    monkeypatch.setattr(config,'config_path',lambda:str(tmp_path/'config.json'))
    monkeypatch.setattr(stats,'_saved_consent_allows',lambda path:True)
    monkeypatch.setattr(stats,'public_model_name',lambda value:normalized.append(value) or stats.LOCAL_MODEL_LABEL)
    monkeypatch.setattr(stats,'_post',lambda url,row,timeout:posted.append(dict(row)))
    row={'status':'finished','model':'example/local/model'}
    assert stats.post_stats_async({'telemetry_opt_in':True,'stats_url':'https://example.invalid/stats'},row)
    assert normalized==[], 'model filesystem/introspection work ran on the caller'
    assert len(pending)==1
    pending[0]()
    assert normalized==['example/local/model']
    assert posted and posted[0]['model']==stats.LOCAL_MODEL_LABEL
    assert row['model']=='example/local/model'
