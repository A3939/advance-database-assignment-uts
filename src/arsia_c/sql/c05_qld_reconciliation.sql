SELECT count(*) FROM pg_temp.c45_crash WHERE
 NULLIF(payload->>'Count_Casualty_Total','')::bigint <>
 NULLIF(payload->>'Count_Casualty_Fatality','')::bigint + NULLIF(payload->>'Count_Casualty_Hospitalised','')::bigint
 + NULLIF(payload->>'Count_Casualty_MedicallyTreated','')::bigint + NULLIF(payload->>'Count_Casualty_MinorInjury','')::bigint;
