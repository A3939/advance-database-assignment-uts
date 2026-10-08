"""Sandbox-only streaming helper. Projection authority remains with host QA."""
import json
from pathlib import Path
from .canonical import project, stable_json
from .table_plan import iter_resource

FILES={"crash":"crashes.jsonl","unit":"units.jsonl","casualty":"casualties.jsonl","observation":"observations.jsonl"}


class AdapterContext:
    def __init__(self,contract,files,output_dir,mode):
        self.contract=contract;self.mode=mode
        self.files={f["id"]:f for f in files}
        self.input_paths={f["id"]:f["path"] for f in files}
        self.output_dir=Path(output_dir)
        self.work_dir=self.output_dir/"work";self.work_dir.mkdir(exist_ok=True)
        self.lookup_projection=None
        if 'lookup_tables' in contract or any(isinstance(r,dict) and 'lookups' in r for r in contract.get('resources',[])):
            from .lookup_projection import LookupProjection
            self.lookup_projection=LookupProjection(contract,files,self.work_dir)
        self.handles={kind:(self.output_dir/name).open("w",encoding="utf-8") for kind,name in FILES.items()}
        self.exclusions=(self.output_dir/"exclusions.jsonl").open("w",encoding="utf-8")
        self.lineage=(self.output_dir/'row-lineage.jsonl').open('w',encoding='utf-8')
        self.preprocessor=None
        self.counts={kind:0 for kind in FILES}

    def iter_rows(self,role):
        resource=next(r for r in self.contract["resources"] if r["role"]==role)
        from .row_preprocessing import enabled, AdapterRows
        collapse=enabled(resource)
        if collapse and self.preprocessor is None:
            self.preprocessor=AdapterRows(self.work_dir/'row-preprocessing.sqlite')
        for index,(locator,row) in enumerate(iter_resource(resource,self.files)):
            if self.mode=="sample" and index>=1000:break
            if collapse:
                receipt,retained=self.preprocessor.row(self.contract,resource,locator,row)
                self.lineage.write(stable_json(receipt)+'\n')
                if not retained:continue
            yield locator,row

    def project(self,role,locator,row):
        if self.lookup_projection is not None:
            return self.lookup_projection.project(role,locator,row)
        return project(self.contract,role,locator,row)

    def emit(self,grain,row):
        if grain not in self.handles:raise ValueError("Unsupported output grain")
        encoded=stable_json(row)
        if len(encoded.encode())>1024*1024:raise ValueError("Canonical record exceeds the 1 MiB row bound")
        self.handles[grain].write(encoded+"\n");self.counts[grain]+=1

    def exclude(self,role,locator,reason):
        if not isinstance(reason,str) or not reason.strip():raise ValueError("Exclusion needs a reason")
        self.exclusions.write(stable_json({"role":role,"row_locator":locator,"reason":reason})+"\n")

    def close(self):
        if self.lookup_projection is not None:self.lookup_projection.close()
        for handle in self.handles.values():handle.close()
        self.exclusions.close()
        self.lineage.close()
        if self.preprocessor is not None:self.preprocessor.close()
