# Direct-execution import fix

The historical experiment scripts import the local `thoughtlab` package. When
Python executes a file nested under `thoughtlab/historicalTests` directly,
Python normally places that nested directory—not the repository root—on
`sys.path`.

This patch bootstraps the repository root before local package imports, so both
forms work from the repo root:

```powershell
python .\thoughtlab\historicalTests\ground_truth_probe.py ...
```

and

```powershell
python -m thoughtlab.historicalTests.ground_truth_probe ...
```
