# Example data

`cf3i_viscosity.json` is an exact copy of `worker/tests/data/cf3i/cf3i_viscosity.json` (published values only; see
`worker/tests/data/cf3i/SOURCE.md` for the citations: Tuhin et al. 2024, Int. J. Thermophys. 45:41; Duan et al. 1999,
Fluid Phase Equilib. 162:303). It drives the "Open the CF3I tutorial" entry of the new-project wizard.
`src/lib/examples.test.ts` fails if the two copies differ.
