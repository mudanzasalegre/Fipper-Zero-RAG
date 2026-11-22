"""CLI wiring for the offline firmware graph. No RF or device operations."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from .firmware_graph import FirmwareGraph
from .sources import index_documents


def add_parser(subparsers):
    top = subparsers.add_parser('firmware', help='Index and interrogate a versioned firmware source graph')
    cmds = top.add_subparsers(dest='fw_action', required=True)
    index = cmds.add_parser('index', help='Index a pinned Git ref from a LOCAL firmware clone')
    index.add_argument('--repo', type=Path, required=True, help='Existing local flipperzero-firmware Git directory')
    index.add_argument('--ref', required=True, help='Official Git tag, dev or exact commit SHA')
    index.add_argument('--max-files', type=int, default=20000)
    index.add_argument('--max-file-bytes', type=int, default=524288)
    index.add_argument('--force', action='store_true')
    index.add_argument('--index-rag', action='store_true', help='Also index symbol summaries into the main RAG search')
    index.add_argument('--rag-limit', type=int, default=1500)
    cmds.add_parser('snapshots', help='List indexed commits, release refs and completeness')
    symbols = cmds.add_parser('symbols', help='Search structured symbols')
    symbols.add_argument('--ref', required=True)
    symbols.add_argument('--query', default='')
    symbols.add_argument('--kind', default='')
    symbols.add_argument('--path-prefix', default='')
    symbols.add_argument('--exported-only', action='store_true')
    symbols.add_argument('--limit', type=int, default=50)
    symbols.add_argument('--offset', type=int, default=0)
    details=cmds.add_parser('symbol', help='Explain a symbol, including incoming and outgoing references')
    details.add_argument('--ref', required=True)
    details.add_argument('--id', required=True)
    refs=cmds.add_parser('refs', help='Find cross references (resolved and unresolved)')
    refs.add_argument('--ref', required=True)
    refs.add_argument('--name', required=True)
    refs.add_argument('--direction', choices=('in','out','both'), default='both')
    graph=cmds.add_parser('graph', help='Traverse resolved links between symbol definitions')
    graph.add_argument('--ref', required=True)
    graph.add_argument('--name', required=True)
    graph.add_argument('--depth', type=int, default=2)
    graph.add_argument('--limit', type=int, default=80)
    exports=cmds.add_parser('exports', help='Query official FAP API symbols table')
    exports.add_argument('--ref', required=True)
    exports.add_argument('--query', default='')
    exports.add_argument('--status', choices=('+','-','?'),default='')
    exports.add_argument('--limit',type=int,default=100)
    compare=cmds.add_parser('compare', help='Compare two indexed firmware refs and API exports')
    compare.add_argument('--before',required=True)
    compare.add_argument('--after',required=True)
    compare.add_argument('--limit',type=int,default=200)
    compare.add_argument('--allow-partial',action='store_true')
    rag=cmds.add_parser('rag-index',help='Index already-scanned source symbols into the RAG')
    rag.add_argument('--ref', required=True)
    rag.add_argument('--limit', type=int, default=1500)
    return top


def run(args, store, embedder):
    graph = FirmwareGraph(store.path)
    action = args.fw_action
    if action == 'index':
        out = graph.index(args.repo, args.ref, max_files=args.max_files,
                          max_file_bytes=args.max_file_bytes, force=args.force)
        if args.index_rag:
            out['rag_index'] = index_documents(store, graph.rag_documents(args.ref, args.rag_limit), embedder)
        return out
    if action == 'snapshots':return {'snapshots':graph.snapshots()}
    if action == 'symbols':
        return graph.symbols(args.ref,query=args.query,kind=args.kind,path_prefix=args.path_prefix,
                             exported_only=args.exported_only,limit=args.limit,offset=args.offset)
    if action == 'symbol':return graph.symbol(args.ref,args.id)
    if action == 'refs':return graph.references(args.ref,args.name,direction=args.direction)
    if action == 'graph':return graph.neighbors(args.ref,args.name,depth=args.depth,limit=args.limit)
    if action == 'exports':return graph.exports(args.ref,query=args.query,status=args.status,limit=args.limit)
    if action == 'compare':return graph.compare(args.before,args.after,limit=args.limit,allow_partial=args.allow_partial)
    if action == 'rag-index':return index_documents(store,graph.rag_documents(args.ref,args.limit),embedder)
    raise ValueError('Unknown firmware graph action')
