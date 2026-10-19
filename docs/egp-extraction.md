# EGP extraction and repacking

From engine 0.3.15 / Workbench preview.30, extraction uses `project.xml` to recover program labels and process-flow membership, matching the useful organization of MagicRoot's extractor. It supports classic PFD process membership, newer container/parent/owner references, namespaced metadata and UTF-8/UTF-16 XML. No MagicRoot installation or SAS connection is required.

In Projects, open Enterprise Guide project tools, select Extract SAS programs and choose an EGP. Leave Output folder blank to use the project name under the workspace, or choose another workspace-relative folder. Existing folders are never overwritten. After completion, Inspect extracted programs opens the file tree; prepare its ZIP to download or copy the entire extraction.

```text
project/
  01 SAS project files/
    2.04 Realised.sas
    2.04 Realised (1).sas
  02 Other files/
    original-egp.zip
    project.xml
    CodeTask-.../code.sas
  03. By process flow/
    Flow name/
      2.04 Realised.sas
  .pysas_egp_manifest.json
```

Names retain spaces and Unicode, with Windows-invalid characters/reserved names sanitized and duplicate names numbered. Long labels are shortened on Windows. If a raw auxiliary path is too long, its original bytes remain in `original-egp.zip` and the console records that exception. The original archive copy may be placed at the extraction root if its auxiliary filename would collide.

SAS source bytes and encodings are preserved. Embedded programs that cannot be matched to metadata are exported to numbered Unknown flow folders instead of being dropped. Missing embedded code for a linked/external program is reported; extraction does not fetch external paths from project metadata. Malformed/missing XML falls back to archive identifiers while retaining every embedded SAS member. Source extraction is staged: errors do not expose a partial destination.

## Repack edited programs

Edit either a program in `01 SAS project files` or its copy in `03. By process flow`, then select Repack extracted programs and the original EGP template. Identical edits in both views are accepted; differing edits stop with a conflict message so neither edit is silently discarded. Auxiliary files are reference copies, not editable aliases. The manifest maps the selected source back to its original archive member; unrelated EGP members are preserved. Existing flat manifests from earlier PySAS versions still work.

Standalone commands remain available:

```powershell
py pysas.py egp extract project.egp --output extracted-project
py pysas.py egp pack extracted-project --template project.egp --output edited-project.egp
```

Unsafe archive/manifest paths, encrypted entries, symbolic links and collisions are rejected. Extraction limits are 20,000 entries, 2 GB total expanded content, 256 MB per member and 16 MB for project.xml. A failed extraction or repack never replaces an existing output.

Reference behavior was compared with [MagicRoot's extractor](https://github.com/HephaestusGodOfFire/magicroot/blob/8e6cb7b/src/magicroot/pysas/extract_egp.py). PySAS's implementation remains standalone and adds safe staging, complete manifests and repacking conflict checks.
