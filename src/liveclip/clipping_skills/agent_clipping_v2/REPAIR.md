# Agent turn repair

Make exactly one schema-valid native function call to a registered tool. Use
the `finish` function only with IDs of artifacts already stored successfully.
Supply every field required by the chosen strict function schema and do not
return prose instead of a function call. Correct only the reported structural
or technical error; do not invent observations or claim an action that no tool
performed.
