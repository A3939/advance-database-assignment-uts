"""Available C/D component bindings; this is not a complete B10 build."""

from arsia_c.canonical import load_canonical
from arsia_c.projections.dispatcher import project
from arsia_d03.facts import runner_callback as load_dw
from arsia_d04.reconciliation import runner_callback as qa_d
from .runner import ModuleBinding
from .vault_load import load_vault


# Upstream implementations remain owned by A, C and D.
BINDING_SPECS = {
    "project": ("arsia_c.projections.dispatcher:project",
                "src/arsia_c/projections/dispatcher.py", "b-cd-project-v1"),
    "vault": ("arsia_ingest.vault_load:load_vault",
              "src/arsia_ingest/vault_load.py", "a06-c0824da"),
    "canonical": ("arsia_c.canonical:load_canonical",
                  "src/arsia_c/canonical.py", "c09-ad8baed"),
    "dw": ("arsia_d03.facts:runner_callback",
           "src/arsia_d03/facts.py", "d03-337101f"),
    "qa_d": ("arsia_d04.reconciliation:runner_callback",
             "src/arsia_d04/reconciliation.py", "d04-337101f"),
}


def bindings():
    """C10 qa_c and E publish must be supplied before a full build."""
    callbacks = {"project": project, "vault": load_vault, "canonical": load_canonical,
                 "dw": load_dw, "qa_d": qa_d}
    return {stage: ModuleBinding(callbacks[stage], path, version)
            for stage, (_, path, version) in BINDING_SPECS.items()}
