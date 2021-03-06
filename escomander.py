#!/usr/bin/env python3

import argparse
import sys

import requests

_sn_tpl = """
Snapshot: {} @ {} - {}
\tIndexes: {}
\tShards: {}/{}
"""


def _get_indices(server, port):
    url = 'http://{}:{}/_cluster/state'.format(server, port)
    ixs = requests.get(url).json()['metadata']['indices'].keys()
    return ixs


def create_snapshot_location(args):
    settings = {
        "type": "fs",
        "settings": {
            "compress": "true",
            "location": "/snapshots/"
        }
    }
    print("Creating snapshot location")
    url = 'http://{}:{}/_snapshot/backup'.format(args.hostname, args.port)
    req = requests.put(url, json=settings)
    res = req.json()
    if 'acknowledged' not in res:
        print(res)
        sys.exit(1)
    assert res['acknowledged'] is True


def _openclose_indices(server, port, close=True):
    ixs = _get_indices(server, port)

    op = {
        False: '_open',
        True: '_close',
    }[close]

    for ix in ixs:
        # print("{} index {}".format(op, ix))
        url = 'http://{}:{}/{}/{}'.format(server, port, ix, op)
        req = requests.post(url)
        res = req.json()
        if res.get('acknowledged') is not True:
            import pdb
            pdb.set_trace()


def make_snapshot(args):
    server = args.hostname
    port = args.port
    name = args.snapshot
    url = ('http://{}:{}/_snapshot/backup/{}?wait_for_completion=true'
           .format(server, port, name))
    res = requests.put(url).json()
    assert 'snapshot' in res
    assert res['snapshot']['state'] == 'SUCCESS'
    print("Snapshot created")


def restore_snapshot(args):
    server = args.hostname
    port = args.port
    name = args.snapshot
    if not name:
        print("Please provide a snapshot name to restore")
        return
    _openclose_indices(server, port, close=True)
    url = 'http://{}:{}/_snapshot/backup/{}/_restore'.format(
        server, port, name)
    res = requests.post(url).json()
    _openclose_indices(server, port, close=False)
    print("Snapshot restored")
    print(res)


def del_all_indexes(args):
    server = args.hostname
    port = args.port
    _openclose_indices(server, port, close=False)
    url = 'http://{}:{}/_all/_settings'.format(server, port)
    all = requests.get(url).json().keys()

    print("This will delete the following indexes: ", ", ".join(all))
    inp = input("Are you sure you want to continue? y/n [n]")
    if inp.lower() != 'y':
        return

    for ix in all:
        print("Deleting {} index ".format(ix))
        url = 'http://{}:{}/{}'.format(server, port, ix)
        req = requests.delete(url)
        assert req.json()['acknowledged'] is True


def show_snapshots(args):
    server = args.hostname
    port = args.port

    print("Showing existing snapshots:\r")
    url = 'http://{}:{}/_snapshot/backup/_all'.format(server, port)
    req = requests.get(url)
    resp = req.json()

    if 'snapshots' not in resp:
        print("No snapshots. ")
        print("Probably need to run <es_commander ... init> first?")
        sys.exit(1)
    snaps = resp['snapshots']
    for sn in snaps:
        print(_sn_tpl.format(
            sn['snapshot'],
            sn['start_time'],
            sn['state'],
            len(sn['indices']),
            sn['shards']['total'],
            sn['shards']['successful']
        ))


def del_snapshots(args):
    server = args.hostname
    port = args.port
    match = args.match
    _openclose_indices(server, port, close=False)

    matches = _get_matching_snapshots(server, port, match)

    print("This will delete the following snapshots: ", ", ".join(matches))
    inp = input("Are you sure you want to continue? y/n [n]")
    if inp.lower() != 'y':
        return

    for ix in matches:
        print("Deleting {} snapshot ".format(ix))
        url = 'http://{}:{}/_snapshot/backup/{}'.format(server, port, ix)
        req = requests.delete(url)
        assert req.json()['acknowledged'] is True


def _get_matching_snapshots(server, port, match):
    url = 'http://{}:{}/_snapshot/backup/_all'.format(server, port)
    req = requests.get(url)
    resp = req.json()
    snaps = resp['snapshots']
    all = [s['snapshot'] for s in snaps if match in s['snapshot']]
    return all


def _get_matching_indexes(server, port, match=""):
    url = 'http://{}:{}/_all/_settings'.format(server, port)
    all = requests.get(url).json().keys()

    matches = []
    for ix in all:
        if match in ix:
            matches.append(ix)

    if not matches:
        print("No matches")
        return []

    return matches


def del_indexes(args):
    server = args.hostname
    port = args.port
    match = args.match
    _openclose_indices(server, port, close=False)

    matches = _get_matching_indexes(server, port, match)

    print("This will delete the following indexes: ", ", ".join(matches))
    inp = input("Are you sure you want to continue? y/n [n]")
    if inp.lower() != 'y':
        return

    for ix in matches:
        print("Deleting {} index ".format(ix))
        url = 'http://{}:{}/{}'.format(server, port, ix)
        req = requests.delete(url)
        assert req.json()['acknowledged'] is True


def del_field(args):
    server = args.hostname
    port = args.port
    field = args.field
    match = args.match
    _openclose_indices(server, port, close=False)
    matches = _get_matching_indexes(server, port, match)

    print(f"This will delete the following field: {field}")
    print("This operation will be performed in the indexes: ",
          ", ".join(matches))

    inp = input("Are you sure you want to continue? y/n [n]")
    if inp.lower() != 'y':
        return

    for ix in matches:
        print("Deleting {} index ".format(ix))
        url = 'http://{}:{}/{}/_update_by_query'.format(server, port, ix)
        settings = {
            "script": {
                "inline": f"ctx._source.remove(\"{field}\")"
            },
            "query": {
                "exists": {"field": field}
            }
        }
        print(settings)
        req = requests.post(url, json=settings)
        print(req.json())


def set_replicas(args):
    server = args.hostname
    port = args.port
    match = args.match

    print("Setting low disk thresholds")
    settings = {
        "persistent": {
            "cluster.routing.allocation.disk.threshold_enabled": False,
            "cluster.routing.allocation.disk.watermark.high": "500mb",
            "cluster.routing.allocation.disk.watermark.low": "500mb",
            "cluster.routing.allocation.disk.watermark.flood_stage": "500mb"
        }
    }
    url = 'http://{}:{}/_cluster/settings'.format(server, port)
    req = requests.put(url, json=settings)

    if not (req.json().get('acknowledged') is True):
        import pdb
        pdb.set_trace()

    assert req.json()['acknowledged'] is True

    if not args.replicas.isdigit():
        print("Please set --replicas to a valid number")
        sys.exit(1)

    replicas = int(args.replicas)
    _openclose_indices(server, port, close=False)
    matches = _get_matching_indexes(server, port, match)

    settings = {
        "index": {"number_of_replicas": replicas},
    }
    for ix in matches:
        url = 'http://{}:{}/{}/_settings'.format(server, port, ix)
        req = requests.put(url, json=settings)
        assert req.json()['acknowledged'] is True


def main():
    handlers = {
        'init': (create_snapshot_location, "Initialize snapshot location"),
        'view': (show_snapshots, "Show existing snapshots"),
        'snapshot': (make_snapshot, "Make a new snapshot"),
        'restore': (restore_snapshot, "Restore a snapshot"),
        'del_all_indexes': (del_all_indexes, "Delete all indexes"),
        'del_index': (del_indexes, "Delete some indexes"),
        'del_snapshots': (del_snapshots, "Delete some snapshots"),
        'del_field': (del_field, "Delete a field"),
        'set_replicas': (set_replicas, "Configure ES: set number of replicas"),
    }

    parser = argparse.ArgumentParser()
    parser.add_argument("hostname", help="Server hostname")
    parser.add_argument("--port", help="Server port", default="9200")

    # TODO: better formatting of help
    parser.add_argument(
        "command",
        help="The command you want performed. One of: \n" +
             ", ".join(handlers.keys())
    )
    parser.add_argument("--snapshot",
                        help="Snapshot name you want restored")
    parser.add_argument("--match",
                        help="Match indexes to delete",
                        default="")
    parser.add_argument("--replicas",
                        help="Number of replicas to set",
                        default="0")
    parser.add_argument("--field",
                        help="Name of the field to delete",
                        default="")
    args = parser.parse_args()

    def fallback(*args):
        print("Not a command")
        return sys.exit(1)

    cmd = args.command
    handlers.get(cmd, [fallback])[0](args)


if __name__ == "__main__":
    main()
