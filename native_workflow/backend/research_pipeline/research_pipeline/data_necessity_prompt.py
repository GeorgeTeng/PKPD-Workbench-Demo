"""Current Necessity prompt; historical accepted executor bindings stay unchanged."""
from pathlib import Path
from . import data_necessity_decisions as contract, data_direct_runtime as rt
from .common import write_json

INSTRUCTIONS = contract.INSTRUCTIONS + '''

Before drafting, allocate the prose budget: the five action decisions need about
300 words; each detailed analysis should use at most 55 words TOTAL across all
prose fields and arrays. Target 900 words overall, safely below the 1100 ceiling.
The short action table already states shared continuation advice; do not repeat
it in every analysis. Preserve distinct scientific conditions in the details.

Group by the measured quantity and affected calculation, not just nearby source
positions or keywords. A censored bacterial response is a PD response, not a PK
concentration or NCA input. If one coverage field spans different endpoint types,
state their distinct effects or choose an accurate shared action such as choosing
endpoint-specific censoring treatment. Keep NCA boundary checks with NCA.
next_action must name a concrete operation, not just an enum or a method name.

Accounting for a gap ID does not account for all its facts: retain every distinct
conflict within that field, even when another source in the group dominates the
main finding. For a reference-only or excluded source, explain the conflict in
details and say that it does not block the selected primary analysis. Do not
promote benchmark observations or targets into primary modeling inputs.

Distinguish an observed response from a paired exposure-response record. A source
with response values but unverified exposure mapping remains a candidate response
source, not a supported target-estimation dataset. State the usable subset and
the held subset explicitly; do not hide this distinction behind 'separately'.
'''


def prepare(coverage_path,main_path,mp_path,out):
    p=contract.prepare(coverage_path,main_path,mp_path,out)
    payload={**p['request']['payload'],'instructions':INSTRUCTIONS}
    p['request']=rt.make_request(payload,payload['schema'])
    p['bindings']['prompt_code']=rt.file_ref(__file__)
    write_json(Path(out)/'prepared.json',p)
    return p
