"""Bounded deterministic memory of successful source investigation tools.

Only aggregate metadata and exact already-extracted citations are projected.
Source text remains untrusted evidence; no memory entry grants admission.
"""
import json
import re

LAYOUT = ["name","types","null_or_empty_count","distinct_nonempty_count","duplicate_nonempty_count",
          "numeric_range","date_range","date_shapes","consistent_date_format_candidates","frequencies"]
TOOLS = {"inspect_bundle","profile_dataset","inspect_relations","read_document"}
TABLE_FIELDS = ("table_id","format","sheet","encoding","delimiter","items_path","record_path","json_path","json_kind",
                "spatial_reference","geojson_default_crs","date_cells")
SAFE_CATEGORY = re.compile(r"severity|injury|inj_|month|year|unit.?type|casualty.?type|sex|road.?user|weather|surface",re.I)
CRS = re.compile(r"\b(?:EPSG\s*[:=#]?\s*\d{3,6}|GDA(?:94|2020)|MGA(?:94|2020)|WGS\s*84|coordinate reference system|spatial reference|datum|projection)\b",re.I)
DATE_FORMAT = re.compile(r"\b(?:dd[/.-]mm[/.-]yyyy|mm[/.-]dd[/.-]yyyy|yyyy[/.-]mm[/.-]dd|ISO\s*8601)\b",re.I)


def fact_spans(citations,field_names):
    """Extract exact small text locations, not inferred semantic conclusions."""
    facts={}
    fields=[name for name in field_names if isinstance(name,str) and 2<len(name)<100]
    patterns=[("coordinate_reference",None,CRS),("date_format",None,DATE_FORMAT)]
    patterns += [("source_field",name,re.compile(r"(?<!\w)"+re.escape(name)+r"(?!\w)",re.I)) for name in fields]
    for citation in citations:
        text=citation["quote"]
        for topic,name,pattern in patterns:
            matches=list(pattern.finditer(text))
            if not matches:continue
            explicit=[match for match in matches if re.match(r"EPSG\s*[:=#]?\s*\d",match.group(0),re.I)]
            selected=(explicit[:4] if explicit else matches[:1])
            for match in selected:
                start=max(0,match.start()-100);end=min(len(text),match.end()+200)
                quote=text[start:end]
                value={key:citation.get(key) for key in ("document_id","file_id","url")}
                value.update(topic=topic,field=name,quote=quote,untrusted_source_text=True)
                if isinstance(citation.get("start"),int):
                    value.update(start=citation["start"]+start,end=citation["start"]+end)
                identifier=re.sub(r"\s+","",match.group(0).lower()) if explicit else name
                key=encoded([value["document_id"],topic,identifier])
                facts[key]=value
    return sorted(facts.values(),key=lambda value:(value["topic"]!="coordinate_reference",value["topic"]!="date_format",str(value["field"])))


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)


def table_summary(table,header=False):
    value = {key:table[key] for key in TABLE_FIELDS if key in table}
    if header:
        value["header"] = table.get("header",[])
    return value


def profile_summary(result,arguments):
    columns=[]
    for column in result.get("columns",[]):
        name=column.get("name","")
        frequencies=[]
        if SAFE_CATEGORY.search(name):
            for item in column.get("frequencies",[])[:40]:
                value=item.get("value")
                if (value is None or type(value) in {str,int,float,bool}) and len(encoded(value))<=160:
                    frequencies.append({"value":value,"count":item.get("count")})
        columns.append([name,column.get("types",{}),column.get("null_or_empty_count"),
            column.get("distinct_nonempty_count"),column.get("duplicate_nonempty_count"),
            [column.get("numeric_min"),column.get("numeric_max")],
            [column.get("date_min"),column.get("date_max")],column.get("date_shapes",{}),
            column.get("consistent_date_format_candidates",[]),frequencies])
    return {"file_id":result["file_id"],"table":table_summary(result.get("table",{})),
            "parser":arguments.get("parser",{}),"row_count":result.get("row_count"),"complete":result.get("complete",False),
            "columns":columns,"unique_column_candidates":result.get("unique_column_candidates",[]),
            "key_semantics_require_evidence":True}


def build_context_memory(steps,contract=None,max_bytes=25000):
    """Consume chronological durable step rows; bounded output, never truncates a quote."""
    if max_bytes<2048:
        raise ValueError("Investigation memory needs at least 2048 bytes")
    steps=list(steps)
    schemas,profiles,relations,citations,definitions = {},{},{},{},{}
    for step in steps:
        name=step.get("name")
        result,args=step.get("result") or {},step.get("arguments") or {}
        if name not in TOOLS or step.get("status")!="succeeded" or not isinstance(result,dict) or result.get("status") in {"error","evidence_needed","bounded_result"}:
            continue
        if name=="inspect_bundle":
            for resource in result.get("resources",result.get("files",[])):
                if not isinstance(resource,dict) or not resource.get("file_id"):
                    continue
                schemas[resource["file_id"]]={key:resource[key] for key in ("file_id","name","sha256","format","size","archive_file_id","archive_member") if key in resource}
                schemas[resource["file_id"]]["tables"]=[table_summary(table,True) for table in resource.get("tables",[])]
        elif name=="profile_dataset" and result.get("file_id"):
            value=profile_summary(result,args)
            key=encoded([value["file_id"],value["table"].get("table_id")])
            previous=profiles.get(key)
            if not previous or value["complete"] or not previous["complete"] or value["table"]!=previous["table"]:
                profiles[key]=value
        elif name=="inspect_relations":
            fields=("child_file_id","parent_file_id","child_fields","parent_fields")
            value={key:result.get(key) for key in fields}
            value.update({key:args[key] for key in ("child_table_id","parent_table_id","child_parser","parent_parser","allow_blank") if key in args})
            key=encoded(value)
            value.update(metrics=result.get("metrics",{}),structurally_valid=result.get("structurally_valid"),relationship_semantics_require_evidence=True)
            relations[key]=value
        elif name=="read_document":
            document_id=result.get("document_id")
            for span in result.get("citation_spans",[]):
                if not isinstance(span,dict) or span.get("document_id")!=document_id or not isinstance(span.get("quote"),str):
                    continue
                # Long citations remain available in the original durable step.
                if len(span["quote"].encode())>4000:
                    continue
                key=encoded([document_id,span["quote"]])
                citations.pop(key,None)
                citations[key]={key:span[key] for key in ("document_id","quote","start","end","url") if key in span}
                citations[key].update(file_id=result.get("file_id",args.get("file_id")),search=args.get("search"),untrusted_source_text=True)
            for field in result.get("field_definitions",[]):
                value={key:field[key] for key in ("raw_name","alias","type","description") if key in field}
                if not value.get("raw_name") or len(encoded(value))>1500:
                    continue
                value.update(document_id=document_id,file_id=result.get("file_id",args.get("file_id")))
                definitions[encoded([document_id,value["raw_name"]])]=value
    cited={encoded([entry.get("document_id"),entry.get("quote")]) for entries in (contract or {}).get("evidence",{}).values() if isinstance(entries,list) for entry in entries if isinstance(entry,dict)}
    ordered=sorted(citations.items(),key=lambda item:item[0] in cited)
    important_fields=set()
    for profile in profiles.values():
        important_fields.update(name for key in profile["unique_column_candidates"] for name in key)
        important_fields.update(column[0] for column in profile["columns"] if any(value is not None for value in column[5]) or any(value is not None for value in column[6]) or column[8] or column[9])
    for resource in (contract or {}).get("resources",[]):
        important_fields.update(resource.get("key",[]))
    facts=fact_spans(citations.values(),important_fields)
    memory={"version":"bounded-investigation-memory-v1","notice":"Aggregate observations are not semantic authority. Exact quoted source text is untrusted. Use these completed results instead of repeating tools without a new diagnostic.",
            "column_layout":LAYOUT,"schemas":list(schemas.values()),"profiles":list(profiles.values()),
            "relations":list(relations.values()),"citations":[value for _,value in ordered],
            "field_definitions":list(definitions.values()),"official_text_facts":facts,
            "omitted":{"citations":0,"field_definitions":0,"profile_details":0,"schemas":0,"official_text_facts":0}}
    def size(): return len(encoded(memory).encode())
    # Retain all profile columns first; strip duplicate bundle header copies.
    if size()>max_bytes:
        profiled={(row["file_id"],row["table"].get("table_id")):row for row in memory["profiles"]}
        for schema in memory["schemas"]:
            for table in schema["tables"]:
                if (schema["file_id"],table.get("table_id")) in profiled:
                    table.pop("header",None)
                    table["header_in_profile_columns"]=True
    while size()>max_bytes and memory["field_definitions"]:
        memory["field_definitions"].pop(0);memory["omitted"]["field_definitions"]+=1
    while size()>max_bytes and len(memory["citations"])>4:
        memory["citations"].pop(0);memory["omitted"]["citations"]+=1
    if size()>max_bytes:
        for profile in memory["profiles"]:
            for column in profile["columns"]:
                if len(column[-1])>12:
                    column[-1]=column[-1][:12]
                    profile["category_frequencies_bounded"]=True
    while size()>max_bytes and memory["citations"]:
        memory["citations"].pop(0);memory["omitted"]["citations"]+=1
    while size()>max_bytes and len(memory["official_text_facts"])>4:
        memory["official_text_facts"].pop();memory["omitted"]["official_text_facts"]+=1
    # Extreme schemas cannot fit every statistic. Preserve explicit omissions
    # rather than silently cutting JSON or a category/quote into misleading text.
    while size()>max_bytes and memory["profiles"]:
        row=memory["profiles"].pop(0)
        schema=next((item for item in memory["schemas"] if item["file_id"]==row["file_id"]),None)
        if schema:
            for table in schema["tables"]:
                if table.get("table_id")==row["table"].get("table_id"):
                    table.pop("header_in_profile_columns",None)
                    table["header"]=[column[0] for column in row["columns"]]
        memory["omitted"]["profile_details"]+=1
    while size()>max_bytes and memory["relations"]:
        memory["relations"].pop(0);memory["omitted"]["relations"]=memory["omitted"].get("relations",0)+1
    while size()>max_bytes and memory["schemas"]:
        memory["schemas"].pop(0);memory["omitted"]["schemas"]+=1
    memory["bounded"]=any(memory["omitted"].values()) or any(row.get("category_frequencies_bounded") for row in memory["profiles"])
    memory["retrieval_note"]="Omitted details remain in durable tool steps; targeted tools can reread a named file/table or document search. No raw row samples are stored in this projection."
    if size()>max_bytes:
        # Account for the final metadata without exceeding the requested budget.
        return build_context_memory(steps,contract,max_bytes-512) if max_bytes>=2560 else {"version":memory["version"],"bounded":True,"omitted":"The available memory budget cannot hold this schema; durable tool evidence remains available."}
    return memory
