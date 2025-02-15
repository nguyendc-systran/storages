import os
import requests_mock
import pytest
import math
import json
import time

import systran_storages

def test_http_storage_get_dir(tmpdir):
    with requests_mock.Mocker() as m:
        m.register_uri(
            "GET", "http://launcher/model/listfile/model0",
            json=[
                {"path": "checkpoint/model.bin", "size": 42},
                {"path": "config.json", "size": 10}])
        m.register_uri(
            "GET", "http://launcher/model/getfile/model0/checkpoint/model.bin", content=b"model")
        m.register_uri(
            "GET", "http://launcher/model/getfile/model0/config.json", content=b"config")
        http = systran_storages.storages.HTTPStorage(
            "0",
            "http://launcher/model/getfile/%s",
            pattern_list="http://launcher/model/listfile/%s")

        local_dir = tmpdir.join("model0")
        http.get("model0", str(local_dir), directory=True)
        assert local_dir.check()
        assert local_dir.join("checkpoint").join("model.bin").read() == "model"
        assert local_dir.join("config.json").read() == "config"


def test_http_stream(tmpdir):
    http = systran_storages.storages.HTTPStorage("0", "http://www.ovh.net/files/%s")
    size = 0
    nchunk = 0
    for chunk in http.stream("1Mio.dat"):
        size += len(chunk)
        nchunk += 1
    assert size == 1024*1024 and nchunk == 1024


def test_storage_manager(tmpdir):
    config = {
                "s3_models": {
                    "description": "model storage on S3",
                    "type": "s3",
                    "bucket": "my-model-storage",
                    "aws_credentials": {
                        "access_key_id": "AAAAAAAAAAAAAAAAAAAA",
                        "secret_access_key": "abcdefghijklmnopqrstuvwxyz0123456789ABCD",
                        "region_name": "us-east-2"
                    },
                    "default_ms": True
                },
                "s3_test": {
                    "description": "some test files",
                    "type": "s3",
                    "bucket": "my-testfiles-storage",
                    "aws_credentials": {
                        "access_key_id": "AAAAAAAAAAAAAAAAAAAA",
                        "secret_access_key": "abcdefghijklmnopqrstuvwxyz0123456789ABCD",
                        "region_name": "us-east-2"
                    }
                },
                "launcher": {
                    "description": "launcher file storage",
                    "type": "http",
                    "get_pattern": "hereget/%s",
                    "post_pattern": "herepost/%s"
                }
    }
    storages = systran_storages.StorageClient(config=config)
    s3_models_storage, path = storages._get_storage("s3_models:pathdir/mysupermodel")
    assert isinstance(s3_models_storage, systran_storages.storages.S3Storage)
    assert path == "pathdir/mysupermodel"
    assert s3_models_storage._storage_id == "s3_models"

    s3_models_storage, path = storages._get_storage("pathdir/mysupermodel", "s3_models")
    assert isinstance(s3_models_storage, systran_storages.storages.S3Storage)

    local_storage, path = storages._get_storage("/pathdir/mysupermodel")
    assert isinstance(local_storage, systran_storages.storages.LocalStorage)
    assert local_storage._storage_id == "local"

    http_storage, path = storages._get_storage("launcher:/hereget/mysupermodel")
    assert isinstance(http_storage, systran_storages.storages.HTTPStorage)
    with pytest.raises(ValueError):
        storages._get_storage("unknown:/hereget/mysupermodel")


def test_local_storage(request, tmpdir):
    storages = systran_storages.StorageClient()
    corpus_dir = str(request.config.rootdir / "corpus")
    storages.get(os.path.join(corpus_dir, "train", "europarl-v7.de-en.10K.tok.de"), str(tmpdir.join("localcopy")))
    assert os.path.isfile(str(tmpdir.join("localcopy")))

    storages.rename(str(tmpdir.join("localcopy")), str(tmpdir.join("localcopy2")))
    assert not os.path.exists(str(tmpdir.join("localcopy")))
    assert os.path.isfile(str(tmpdir.join("localcopy2")))

    storages.delete(str(tmpdir.join("localcopy2")))
    assert not os.path.exists(str(tmpdir.join("localcopy2")))

    # cannot transfer directory if not in remote mode
    with pytest.raises(Exception):
        storages.get(corpus_dir, str(tmpdir.join("localdir")))

    storages.get(corpus_dir, str(tmpdir.join("localdir")), directory=True)
    assert os.path.isfile(str(tmpdir.join("localdir", "train", "europarl-v7.de-en.10K.tok.de")))

    with pytest.raises(ValueError):
        storages.delete(str(tmpdir.join("localdir")))
    storages.delete(str(tmpdir.join("localdir")), recursive=True)
    assert not os.path.exists(str(tmpdir.join("localdir")))


def test_local_ls(request, tmpdir):
    localstorage = systran_storages.storages.LocalStorage()
    with pytest.raises(Exception):
        lsdir = localstorage.listdir(str(request.config.rootdir / "nothinghere"))
    lsdir = localstorage.listdir(str(request.config.rootdir / "corpus"))
    assert len(lsdir) == 3
    assert str(pytest.config.rootdir / "corpus" / "train")+"/" in lsdir
    assert str(pytest.config.rootdir / "corpus" / "vocab")+"/" in lsdir
    assert str(pytest.config.rootdir / "corpus" / "eval")+"/" in lsdir
    lsdirrec = localstorage.listdir(str(request.config.rootdir / "corpus"), True)
    assert len(lsdirrec) > len(lsdir)

def test_storages(request, tmpdir, storages, storage_id):
    if storage_id.startswith('_'):
        return
    corpus_dir = str(request.config.rootdir / "corpus")

    storage_client = systran_storages.StorageClient(config=storages)

    with open(os.path.join(corpus_dir, "vocab", "en-vocab.txt"), "rb") as f:
        en_vocab = f.read()

    stor_tmp_dir = str(tmpdir.join("test_storages", storage_id))
    os.makedirs(stor_tmp_dir)
    # checking if the root is here
    assert storage_client.exists("/", storage_id=storage_id)
    # checking the main directory is here
    maindir_exists = storage_client.exists(os.path.join("myremotedirectory"),
                                           storage_id=storage_id)
    # first deleting directory - if it exists
    try:
        print("==> delete myremotedirectory")
        storage_client.delete(os.path.join("myremotedirectory"),
                              recursive=True,
                              storage_id=storage_id)
    except Exception as e:
        assert not maindir_exists, "cannot remove main directory (%s)" % str(e)
    # checking the directory is not there anymore
    assert not storage_client.exists(os.path.join("myremotedirectory"),
                                     storage_id=storage_id)
    # pushing a file to a directory
    storage_client.push(os.path.join(corpus_dir, "train", "europarl-v7.de-en.10K.tok.de"),
                        "myremotedirectory/",
                        storage_id=storage_id)
    # checking directory and files are created
    assert storage_client.exists(os.path.join("myremotedirectory"),
                                 storage_id=storage_id)
    assert storage_client.exists(os.path.join("myremotedirectory", "europarl-v7.de-en.10K.tok.de"),
                                 storage_id=storage_id)
    # pushing a file to a new file
    storage_client.push(os.path.join(corpus_dir, "train", "europarl-v7.de-en.10K.tok.de"),
                        os.path.join("myremotedirectory", "test", "copy-europarl-v7.de-en.10K.tok.de"),
                        storage_id=storage_id)
    # pushing a file to a new file on a completely new directory
    if storage_client.exists(storage_id+":"+os.path.join("myremotedirectory-new/")):
        storage_client.delete(os.path.join("myremotedirectory-new"),
                              recursive=True,
                              storage_id=storage_id)
    if storages[storage_id]["type"] == "local" and "basedir" not in storages[storage_id]:
        # access to absolute path for local storage without basedir means absolute path... this won't work
        with pytest.raises(Exception):
            storage_client.push(os.path.join(corpus_dir, "train", "europarl-v7.de-en.10K.tok.de"),
                                os.path.join("/myremotedirectory-new", "test-new", "copy-europarl-v7.de-en.10K.tok.de"),
                                storage_id=storage_id)
        storage_client.push(os.path.join(corpus_dir, "train", "europarl-v7.de-en.10K.tok.de"),
                            os.path.join("myremotedirectory-new", "test-new", "copy-europarl-v7.de-en.10K.tok.de"),
                            storage_id=storage_id)
    else:
        storage_client.push(os.path.join(corpus_dir, "train", "europarl-v7.de-en.10K.tok.de"),
                            os.path.join("/myremotedirectory-new", "test-new", "copy-europarl-v7.de-en.10K.tok.de"),
                            storage_id=storage_id)
    # renaming a file
    storage_client.rename(os.path.join("myremotedirectory", "test", "copy-europarl-v7.de-en.10K.tok.de"),
                          os.path.join("myremotedirectory", "test", "copy2-europarl-v7.de-en.10K.tok.de"),
                          storage_id=storage_id)
    # pushing a full directory
    storage_client.push(os.path.join(corpus_dir, "vocab"),
                        os.path.join("myremotedirectory", "vocab"),
                        storage_id=storage_id)
    # getting a file back into local temp directory
    storage_client.get(os.path.join("myremotedirectory", "vocab", "en-vocab.txt"),
                       os.path.join(stor_tmp_dir),
                       storage_id=storage_id)
    assert os.path.exists(os.path.join(stor_tmp_dir, "en-vocab.txt"))

    # getting it back again, should use cache so not modify the file
    # to check cache modify, first byte of the file keeping it mtime
    stat = os.stat(os.path.join(stor_tmp_dir, "en-vocab.txt"))
    time.sleep(1)
    storage_client.get(os.path.join("myremotedirectory", "vocab", "en-vocab.txt"),
                       os.path.join(stor_tmp_dir),
                       storage_id=storage_id)
    new_stat = os.stat(os.path.join(stor_tmp_dir, "en-vocab.txt"))
    assert stat.st_mtime == new_stat.st_mtime, "file should not have changed"

    os.remove(os.path.join(stor_tmp_dir, "en-vocab.txt"))
    # renaming a directory
    storage_client.rename(os.path.join("myremotedirectory", "vocab"),
                          os.path.join("myremotedirectory", "vocab-2"),
                          storage_id=storage_id)
    # getting the file from renamed directory back into local temp directory
    storage_client.get(os.path.join("myremotedirectory", "vocab-2", "en-vocab.txt"),
                       os.path.join(stor_tmp_dir),
                       storage_id=storage_id)
    assert os.path.isfile(os.path.join(stor_tmp_dir, "en-vocab.txt"))
    with open(os.path.join(stor_tmp_dir, "en-vocab.txt"), "rb") as f:
        back_en_vocab = f.read()
    assert back_en_vocab == en_vocab
    # getting an inexisting file
    with pytest.raises(Exception):
        storage_client.get(os.path.join("myremotedirectory", "vocab-2", "troc"),
                           os.path.join(stor_tmp_dir, "troc"),
                           storage_id=storage_id)
    # streaming a file back
    size = 0
    nchunk = 0
    generator = storage_client.stream(os.path.join("myremotedirectory", "vocab-2", "en-vocab.txt"),
                                      buffer_size=100,
                                      storage_id=storage_id)
    for chunk in generator:
        size += len(chunk)
        nchunk += 1
    assert size == len(en_vocab)
    assert nchunk >= int(math.ceil(len(en_vocab)/100.))
    # deleting a file
    storage_client.delete(os.path.join("myremotedirectory", "vocab-2", "en-vocab.txt"),
                          storage_id=storage_id)
    assert not storage_client.exists(os.path.join("myremotedirectory", "vocab-2", "en-vocab.txt"),
                                     storage_id=storage_id)
    # checking ls
    lsdir = sorted(storage_client.listdir(os.path.join("myremotedirectory/"),
                                          storage_id=storage_id))
    assert lsdir == ['myremotedirectory/europarl-v7.de-en.10K.tok.de',
                     'myremotedirectory/test/',
                     'myremotedirectory/vocab-2/']
    # checking ls
    lsdir = sorted(storage_client.listdir(os.path.join("myremotedirectory/"),
                                          recursive=True,
                                          storage_id=storage_id))
    assert lsdir == ['myremotedirectory/europarl-v7.de-en.10K.tok.de',
                     'myremotedirectory/test/copy2-europarl-v7.de-en.10K.tok.de',
                     'myremotedirectory/vocab-2/de-vocab.txt']
    # getting directory back
    with pytest.raises(Exception):
        storage_client.get(os.path.join("myremotedirectory"),
                           os.path.join(stor_tmp_dir),
                           storage_id=storage_id)
    storage_client.get(os.path.join("myremotedirectory"),
                       os.path.join(stor_tmp_dir, "myremotedirectory"),
                       directory=True,
                       storage_id=storage_id)
    storage_client.get(os.path.join("myremotedirectory"),
                       os.path.join(stor_tmp_dir, "myremotedirectory"),
                       directory=None,
                       storage_id=storage_id)
    local_listdir = sorted([f for f in os.listdir(os.path.join(stor_tmp_dir, "myremotedirectory"))
                            if not f.endswith('#md5')])
    # deleting full directory
    storage_client.delete(os.path.join("myremotedirectory"),
                          recursive=True,
                          storage_id=storage_id)
    # checking directory is not there anymore
    assert not storage_client.exists(os.path.join("myremotedirectory"),
                                     storage_id=storage_id)

def test_is_managed_path():
    config = {"s3_models": {}, "s3_test": {}, "launcher": {}}
    client = systran_storages.StorageClient(config=config)
    assert not client.is_managed_path("/home/ubuntu/file.txt")
    assert not client.is_managed_path(":ubuntu/file.txt")
    assert not client.is_managed_path("storage:ubuntu/file.txt")
    assert client.is_managed_path("s3_models:ubuntu/file.txt")
    assert client.is_managed_path("s3_test:")
