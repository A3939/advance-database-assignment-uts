"""Offline research/replay CLI. No automatic DB, network or model calls."""
import argparse
import json
from pathlib import Path

from .source_knowledge import file_hash, lookup, inspect_files, metadata_projection, semantic_diff, read_evidence


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('catalog');q.add_argument('--dataset-id');q.add_argument('--jurisdiction');q.add_argument('--resource-id')
    q=sub.add_parser('evidence');q.add_argument('evidence_id');q.add_argument('--locator');q.add_argument('--offset',type=int,default=0)
    q=sub.add_parser('inspect');q.add_argument('files',nargs='+',type=Path)
    q=sub.add_parser('diff');q.add_argument('provider',choices=['ckan','socrata','arcgis']);q.add_argument('before',type=Path);q.add_argument('after',type=Path)
    q=sub.add_parser('replay-native');q.add_argument('--output',required=True,type=Path);q.add_argument('files',nargs='+',type=Path)
    args=p.parse_args()
    if args.command=='catalog':
        result=lookup(dataset_id=args.dataset_id,jurisdiction=args.jurisdiction,resource_id=args.resource_id)
    elif args.command=='evidence':result=read_evidence(args.evidence_id,locator=args.locator,offset=args.offset)
    elif args.command=='diff':
        result=semantic_diff(*(metadata_projection(json.loads(f.read_text()),args.provider) for f in [args.before,args.after]))
    else:
        files=[{'id':f'file-{i}','name':f.name,'path':str(f.resolve()),'sha256':file_hash(f),'size':f.stat().st_size} for i,f in enumerate(args.files)]
        if args.command=='inspect':result=inspect_files(files)
        else:
            if args.output.exists() or args.output.is_symlink():p.error('Use a fresh output directory; prior evidence is preserved')
            args.output.mkdir(parents=True,mode=0o700)
            from .processing import process_bundle
            result=process_bundle(files,args.output,{},lambda *a,**k:None,lambda:None)
            result={k:result[k] for k in ('source_id','summary','qa','fingerprint')}
            result.update(model_calls=0,published=False,output=str(args.output.resolve()))
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))


if __name__=='__main__':main()
