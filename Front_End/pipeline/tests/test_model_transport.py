"""No arbitrary gateway URL, normal task redirection or foreign socket adoption."""
import os
from pathlib import Path
import socket
from uuid import uuid4
import pytest
from arsia_pipeline.config import RuntimeConfigurationError
from arsia_pipeline.model_transport import connection,socket_path


def test_normal_transport_stays_on_the_existing_fixed_loopback():
    conn=connection({},5)
    assert conn.host=='127.0.0.1' and conn.port==3100 and conn.timeout==5
    conn.close()


def test_unmanaged_config_cannot_select_a_test_gateway():
    with pytest.raises(RuntimeConfigurationError):connection({'private_model_gateway':{'socket_path':'/tmp/other.sock'}},5)


def test_socket_requires_exact_instance_private_owner_and_task_path():
    session=uuid4().hex;directory=Path('/tmp').resolve()/('arsia-model-'+session[:12]);directory.mkdir(mode=0o700)
    path=directory/'gateway.sock';listener=socket.socket(socket.AF_UNIX);listener.bind(str(path));path.chmod(0o600)
    cfg={'instance_id':'test-instance','test_session_id':session,'storage_policy':{'enabled':True},
         'private_model_gateway':{'protocol':'owned-model-gateway-v1','instance_id':'test-instance','test_session_id':session,'socket_path':str(path)}}
    try:
        assert socket_path(cfg)==str(path)
        for key,value in [('instance_id','another-instance'),('test_session_id','0'*32),('socket_path',str(directory/'wrong.sock'))]:
            with pytest.raises(RuntimeConfigurationError):socket_path({**cfg,'private_model_gateway':{**cfg['private_model_gateway'],key:value}})
        path.chmod(0o666)
        with pytest.raises(RuntimeConfigurationError):socket_path(cfg)
        path.chmod(0o600);directory.chmod(0o755)
        with pytest.raises(RuntimeConfigurationError):socket_path(cfg)
    finally:listener.close();directory.chmod(0o700)
