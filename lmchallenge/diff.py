# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT license.

'''Compare a pair of LM Challenge log files, which were generated by
 different models (or settings) but over the same text.
'''

import click
from .core import common
from . import pretty, stats


class RenderCompletion:
    '''Pretty-print a token to show difference in
    next-word-prediction/completion.

    +-------------+-------------+--------------+
    | Baseline    | Log         | Color        |
    +=============+=============+==============+
    | Predicted   | Predicted   | Black (Grey) |
    | Unpredicted | Unpredicted | Default      |
    +-------------+-------------+--------------+
    | Unpredicted | Predicted   | Bold Green  -|
    | Predicted   | Unpredicted | Bold Red     |
    +-------------+-------------+--------------+
    '''
    @staticmethod
    def ntyped(target, completions):
        return next(
            (i
             for i, cs in enumerate(completions)
             if ((common.rank(cs, target[i:]) or float('inf'))
                 <= (3 if i == 0 else 2))),
            len(target))

    def __call__(self, datum, out):
        base = self.ntyped(datum['target'], datum['baseline']['completions'])
        ntyped = self.ntyped(datum['target'], datum['log']['completions'])
        n = min(base, ntyped)
        out.color(out.BLACK, bold=False)
        out.write(datum['target'][:n])
        if base < ntyped:
            out.color(out.RED, bold=True)
        elif ntyped < base:
            out.color(out.GREEN, bold=True)
        else:
            out.color(out.DEFAULT, bold=False)
        out.write(datum['target'][n:])


class RenderEntropy:
    '''Pretty-print a token to show entropy difference.

        +--------------------+------------+
        | Entropy difference | Color      |
        +====================+============+
        |       Skip         | Blue       |
        +--------------------+------------+
        |      Unknown       | Magenta    |
        |  Unknown -> Known  | White      |
        |  Known -> Unknown  | Bold White |
        +--------------------+------------+
        |    +i/2 - ...      | Bold Green |
        |    +i/6 - +i/2     | Green      |
        |    -i/6 - +i/6     | Yellow     |
        |    -i/2 - -i/6     | Red        |
        |     ... - -i/2     | Bold Red   |
        +--------------------+------------+
    '''
    def __init__(self, interval):
        self._interval = interval

    def __call__(self, datum, out):
        base = datum['baseline']['logp']
        logp = datum['log']['logp']
        if (base, logp) == (None, None):
            out.color(out.MAGENTA, bold=False)
        elif logp is None or base is None:
            out.color(out.WHITE, bold=(logp is None))
        else:
            diff = logp - base
            x = self._interval / 6
            if 3 * x < diff:
                out.color(out.GREEN, True)
            elif x < diff:
                out.color(out.GREEN, False)
            elif -x < diff:
                out.color(out.YELLOW, False)
            elif -3 * x < diff:
                out.color(out.RED, False)
            else:
                out.color(out.RED, True)
        out.write(datum['target'])


class RenderReranking:
    '''Pretty-print a token to show correction difference.

        +--------------+--------------+-------------+
        | Baseline     | Log          | Color       |
        +==============+==============+=============+
        |             Skip            | Blue        |
        +--------------+--------------+-------------+
        |          Unchanged          | Black       |
        |          Corrected          | Black       |
        |         Uncorrected         | Bold Black  |
        |         Miscorrected        | Bold Black  |
        +--------------+--------------+-------------+
        | Miscorrected | Unchanged    | Bold Green  |
        | Unchanged    | Miscorrected | Bold Red    |
        +--------------+--------------+-------------+
        | Uncorrected  | Corrected    | Green       |
        | Corrected    | Uncorrected  | Red         |
        +--------------+--------------+-------------+
    '''
    def __init__(self, base_model, model):
        self._base_model = base_model
        self._model = model

    def __call__(self, datum, out):
        target = datum['target']
        base_results = datum['baseline']['results']
        pre = pretty.RenderReranking.is_correct(
            target, base_results, lambda e, lm: e)
        base = pretty.RenderReranking.is_correct(
            target, base_results, self._base_model)
        post = pretty.RenderReranking.is_correct(
            target, datum['log']['results'], self._model)

        # Changed base->post
        if (pre, base, post) == (True, True, False):
            # unchanged -> miscorrected
            out.color(out.RED, bold=True)
        elif (pre, base, post) == (False, True, False):
            # corrected -> uncorrected
            out.color(out.RED, bold=False)
        elif (pre, base, post) == (True, False, True):
            # miscorrected -> unchanged
            out.color(out.GREEN, bold=True)
        elif (pre, base, post) == (False, False, True):
            # uncorrected -> corrected
            out.color(out.GREEN, bold=False)

        # Unchanged base->post
        elif (base, post) == (False, False):
            # miscorrected/uncorrected
            out.color(out.BLACK, bold=True)
        elif (base, post) == (True, True):
            # corrected/unchanged
            out.color(out.BLACK, bold=False)

        else:
            assert False, '(should be) unreachable code'

        out.write(datum['target'])


# Script

class ChallengeChoice(common.ChallengeChoice):
    '''Select a pretty printing program.
    '''
    @staticmethod
    def completion(baseline, log, **args):
        return pretty.render_ansi(
            common.zip_logs(baseline=baseline, log=log),
            RenderCompletion())

    @staticmethod
    def entropy(baseline, log, entropy_interval, **args):
        return pretty.render_ansi(
            common.zip_logs(baseline=baseline, log=log),
            RenderEntropy(interval=entropy_interval))

    @staticmethod
    def reranking(baseline, log, **args):
        baseline = list(baseline)
        log = list(log)
        return pretty.render_ansi(
            common.zip_logs(baseline=baseline, log=log),
            RenderReranking(
                base_model=stats.Reranking.build_model(baseline),
                model=stats.Reranking.build_model(log)))


@click.command()
@click.argument('baseline', type=click.Path(dir_okay=False))
@click.argument('log', type=click.Path(dir_okay=False))
@click.option('-v', '--verbose', default=0, count=True,
              help='How much human-readable detail to print to STDERR')
@click.option('-c', '--challenge', type=ChallengeChoice(),
              default='auto',
              help='Select which challenge to view (in the case where there'
              ' are multiple challenges in a single log)')
@click.option('-i', '--entropy_interval', default=10.0,
              help='Interval to show entropy differences over (should be'
              ' positive)')
def cli(baseline, log, verbose, challenge, entropy_interval):
    '''Pretty-print a comparison of two result logs from LM Challenge
    (using ANSI color codes).
    '''
    common.verbosity(verbose)

    for line in challenge(
            common.load_jsonlines(baseline),
            common.load_jsonlines(log),
            entropy_interval=entropy_interval):
        print(line)


__doc__ += common.shell_docstring(cli, 'lmc diff')
if __name__ == '__main__':
    cli()
