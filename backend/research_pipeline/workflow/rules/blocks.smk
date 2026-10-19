def block_inputs(wc):
    step = STEPS[wc.stage]
    return ([step['contract']] + step['external_inputs'] +
            [RECEIPTS + '/' + name + '.json' for name in step['depends']])

rule block:
    input: block_inputs
    output: RECEIPTS + '/{stage}.json'
    wildcard_constraints: stage='(?:' + '|'.join(STEPS) + ')'
    threads: lambda wc: STEPS[wc.stage]['slots']
    params: contract=lambda wc: STEPS[wc.stage]['contract']
    run:
        subprocess.run([sys.executable, '-I', '-X', 'utf8', '-m',
                        'research_pipeline.workflow_runtime', params.contract], check=True)
