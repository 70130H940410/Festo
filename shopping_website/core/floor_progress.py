"""Read-only projection of recorded per-piece progress onto the factory floor."""
import re


def project_pieces(amount, steps, rows, failures):
    result = []
    for number in range(1, amount + 1):
        recorded = {r['step_order']: r for r in rows if r['piece_no'] == number}
        ordered = [(s, recorded.get(s['step_order'])) for s in steps]
        started = [(s, r) for s, r in ordered if r and r['state'] in ('running', 'error')]
        finished = [(s, r) for s, r in ordered if r and r['state'] == 'finished']
        complete = bool(steps) and len(finished) == len(steps)
        selected = started[0] if started else finished[-1] if finished else None
        state = 'finished' if complete else 'pending'
        code, step_name = None, None
        if selected:
            step, row = selected
            match = re.search(r'/\s*(A1|A2|[B-H])\s*\)', step.get('station') or '')
            code = match.group(1) if match else None
            step_name = step['step_name']
            if started:
                state = 'error' if (number, step['step_order']) in failures else row['state']
            elif not complete:
                state = 'waiting'
        if not recorded or not steps:
            state = 'unknown'
        # Finished processing steps are not evidence of the classifier's product class.
        result.append(dict(piece_no=number, station=code, state=state,
                           step_name=step_name, done_steps=len(finished), total_steps=len(steps)))
    return result
