"""Independent checks of the rat PMB 2C NLME candidate (nlmixr2 FOCEI, round 1, attempt 1).

Reads only the files the pipeline produced (engine_data.csv, predictions.csv,
covariance.csv, omega.csv, fit_summary.txt values). It does not refit the
population model. Checks:
  1. Verification: re-derive IPRED from each rat's post hoc parameters with an
     independent closed-form/matrix-exponential 2C infusion solution.
  2. Condition numbers of the covariance and correlation matrices.
  3. Simulation-based VPC / NPC / NPDE-style (pde) check with the estimated
     typical values, diagonal omega and nlmixr2 combined2 residual error.
  4. Per-rat NCA (linear-up/log-down) as a model-independent cross-check of CL,
     Vss and the extrapolated fraction of AUC.
  5. Terminal-phase support: model half-lives vs. the 6 h sampling window.
  6. Exploratory: NPC again with the CL-VC correlation seen in the post hoc etas
     (same estimates, not a refit).

Usage (from the repository root, with the review package run folder):
  python diagnostics/rat_model_checks.py <attempt_folder> <output_folder>
  e.g. <attempt_folder> = outputs/Workbench_Preview_v22/runs/RAT_PK_REVIEW_20260923/
       animal_pk/round_01/candidates/RAT_S21_IV_2C_combined/attempts/1
Requires numpy>=2.0, pandas, scipy. Parameter values below are those of that
attempt; update THETA / residual SDs when checking a different fit.
Written 2026-09-24 as an independent reviewer check; not part of the pipeline.
"""
import json, math, sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.linalg import expm
from scipy import stats

if len(sys.argv) < 3:
    sys.exit(__doc__)
BASE = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(20260924)

data = pd.read_csv(BASE / 'engine_data.csv')
pred = pd.read_csv(BASE / 'predictions.csv')
dose = data[data.EVID == 1].set_index('ID')
obs = data[data.EVID == 0].copy()

# ---------------- model -----------------
def conc_2c(t, cl, v1, q, v2, amt, dur):
    """Central concentration of a linear 2C model after one zero-order infusion."""
    K = np.array([[-(cl + q) / v1, q / v2], [q / v1, -q / v2]])
    rate = amt / dur
    b = np.array([rate, 0.0])
    Kinv = np.linalg.inv(K)
    out = []
    x_end = Kinv @ (expm(K * dur) - np.eye(2)) @ b  # state at end of infusion
    for ti in np.atleast_1d(t):
        if ti <= dur:
            x = Kinv @ (expm(K * ti) - np.eye(2)) @ b
        else:
            x = expm(K * (ti - dur)) @ x_end
        out.append(x[0] / v1)
    return np.array(out)

# 1. verification of IPRED
rows = []
for sid, g in pred.groupby('ID'):
    p = g.iloc[0]
    amt = dose.loc[sid, 'AMT']; dur = amt / dose.loc[sid, 'RATE']
    ip = conc_2c(g.TIME.values, p.cl, p.vc, p.q, p.vp, amt, dur)
    rows.append(np.abs(ip - g.IPRED.values) / g.IPRED.values)
rel = np.concatenate(rows)
verification = {'n_predictions': int(rel.size), 'max_relative_difference_IPRED': float(rel.max()),
                'median_relative_difference_IPRED': float(np.median(rel))}

# 2. condition numbers
cov = pd.read_csv(BASE / 'covariance.csv', index_col=0)
ev = np.linalg.eigvalsh(cov.values)
d = np.sqrt(np.diag(cov.values)); cor = cov.values / np.outer(d, d)
evc = np.linalg.eigvalsh(cor)
struct = ['tcl', 'tvc', 'tq', 'tvp']
cs = cov.loc[struct, struct].values; ds = np.sqrt(np.diag(cs)); cors = cs / np.outer(ds, ds)
conditioning = {'condition_number_covariance_all': float(ev.max() / ev.min()),
                'condition_number_correlation_all': float(evc.max() / evc.min()),
                'condition_number_correlation_structural': float(np.linalg.eigvalsh(cors).max() / np.linalg.eigvalsh(cors).min()),
                'max_abs_correlation_all_parameters': float(np.max(np.abs(cor[np.triu_indices_from(cor, 1)]))),
                'pairs_abs_corr_gt_0.8': [
                    [cov.index[i], cov.index[j], round(float(cor[i, j]), 3)]
                    for i in range(len(cor)) for j in range(i + 1, len(cor)) if abs(cor[i, j]) > 0.8]}

# 3. simulation-based checks
theta = dict(cl=0.195420337966785, vc=0.245863216260808, q=0.186339319181926, vp=0.118623671739409)
omega = pd.read_csv(BASE / 'omega.csv', index_col=0)
om_cl, om_vc = omega.loc['eta.cl', 'eta.cl'], omega.loc['eta.vc', 'eta.vc']
add_sd, prop_sd = 0.0313, 0.128  # fit_summary.txt (3 significant figures)
NREP = 1000
design = {sid: g.TIME.values for sid, g in obs.groupby('ID')}
sims = {sid: np.empty((NREP, len(t))) for sid, t in design.items()}
for r in range(NREP):
    for sid, t in design.items():
        cl = theta['cl'] * math.exp(rng.normal(0, math.sqrt(om_cl)))
        vc = theta['vc'] * math.exp(rng.normal(0, math.sqrt(om_vc)))
        amt = dose.loc[sid, 'AMT']; dur = amt / dose.loc[sid, 'RATE']
        f = conc_2c(t, cl, vc, theta['q'], theta['vp'], amt, dur)
        sd = np.sqrt(add_sd ** 2 + (prop_sd * f) ** 2)  # nlmixr2 combined2
        sims[sid][r] = f + rng.normal(0, 1, len(t)) * sd

# pde per observation, NPC coverage
pdes, inside90, inside50, below5, above95 = [], 0, 0, 0, 0
per_time = {}
for sid, g in obs.groupby('ID'):
    s = sims[sid]
    for j, (t, dv) in enumerate(zip(g.TIME.values, g.DV.values)):
        col = s[:, j]
        pde = (np.sum(col < dv) + 0.5 * np.sum(col == dv)) / NREP
        pdes.append(pde)
        lo5, lo25, hi75, hi95 = np.percentile(col, [5, 25, 75, 95])
        inside90 += lo5 <= dv <= hi95; inside50 += lo25 <= dv <= hi75
        below5 += dv < lo5; above95 += dv > hi95
        per_time.setdefault(round(t, 2), []).append((dv, pde))
pdes = np.clip(np.array(pdes), 1 / (2 * NREP), 1 - 1 / (2 * NREP))
npde = stats.norm.ppf(pdes)
n = len(pdes)
npc = {'n_obs': n, 'observed_within_90PI_pct': 100 * inside90 / n, 'expected_90PI_pct': 90,
       'observed_within_50PI_pct': 100 * inside50 / n, 'below_5th_pct': 100 * below5 / n,
       'above_95th_pct': 100 * above95 / n,
       'binomial_95_range_for_5pct_tail': [100 * stats.binom.ppf(0.025, n, 0.05) / n, 100 * stats.binom.ppf(0.975, n, 0.05) / n]}
npde_stats = {'mean': float(npde.mean()), 'variance': float(npde.var(ddof=1)),
              't_test_p_mean0': float(stats.ttest_1samp(npde, 0).pvalue),
              'shapiro_p': float(stats.shapiro(npde).pvalue),
              'note': 'Observations within a rat are correlated; decorrelation of the full NPDE method was not applied (pde-level check).'}

# VPC by nominal time bins (observed percentiles vs simulated percentile CIs)
obs['bin'] = obs.TIME.round(2)
vpc_rows = []
for b, g in obs.groupby('bin'):
    idx = {sid: list(design[sid]).index(t) for sid, t in zip(g.ID, g.TIME)}
    sim_mat = np.column_stack([sims[sid][:, idx[sid]] for sid in g.ID])  # NREP x n_in_bin
    sim_p = np.percentile(sim_mat, [5, 50, 95], axis=1)  # 3 x NREP
    obs_p = np.percentile(g.DV.values, [5, 50, 95])
    row = {'time_h': b, 'n_obs': len(g)}
    for k, lab in enumerate(['p05', 'p50', 'p95']):
        lo, hi = np.percentile(sim_p[k], [2.5, 97.5])
        row[f'obs_{lab}'] = obs_p[k]; row[f'sim_{lab}_CI_lo'] = lo; row[f'sim_{lab}_CI_hi'] = hi
        row[f'{lab}_outside_CI'] = bool(obs_p[k] < lo or obs_p[k] > hi)
    vpc_rows.append(row)
vpc = pd.DataFrame(vpc_rows)
vpc.to_csv(OUT / 'rat_2C_combined_vpc.csv', index=False)

# 4. NCA per rat
def nca(t, c, amt, dur):
    t = np.asarray(t); c = np.asarray(c)
    auc = aumc = 0.0
    tt = np.concatenate([[0], t]); cc = np.concatenate([[0], c])
    for i in range(1, len(tt)):
        dt = tt[i] - tt[i - 1]
        if cc[i] < cc[i - 1] and cc[i] > 0 and cc[i - 1] > 0:
            k = math.log(cc[i - 1] / cc[i]) / dt
            a = (cc[i - 1] - cc[i]) / k
            auc += a
            aumc += (tt[i - 1] * cc[i - 1] - tt[i] * cc[i]) / k + (cc[i - 1] - cc[i]) / k ** 2
        else:
            auc += dt * (cc[i] + cc[i - 1]) / 2
            aumc += dt * (tt[i] * cc[i] + tt[i - 1] * cc[i - 1]) / 2
    best = None
    for m in range(3, min(6, len(t)) + 1):
        x = t[-m:]; y = np.log(c[-m:])
        sl, ic, rv, _, _ = stats.linregress(x, y)
        adj = 1 - (1 - rv ** 2) * (m - 1) / (m - 2)
        if sl < 0 and (best is None or adj > best[1] + 1e-4):
            best = (-sl, adj, m)
    lz, adjr2, m = best
    clast = c[-1]; tlast = t[-1]
    aucinf = auc + clast / lz
    aumcinf = aumc + clast * tlast / lz + clast / lz ** 2
    mrt = aumcinf / aucinf - dur / 2
    cl = amt / aucinf
    return dict(AUClast=auc, AUCinf=aucinf, pct_extrap=100 * (clast / lz) / aucinf, lambda_z=lz,
                t_half=math.log(2) / lz, adjR2=adjr2, n_lz=m, CL=cl, Vss=cl * mrt, tlast=tlast)

nca_rows = []
post = pred.groupby('ID').first()
for sid, g in obs.groupby('ID'):
    amt = dose.loc[sid, 'AMT']; dur = amt / dose.loc[sid, 'RATE']
    r = nca(g.TIME.values, g.DV.values, amt, dur); r['ID'] = sid
    r['CL_posthoc_NLME'] = post.loc[sid, 'cl']
    p = post.loc[sid]
    r['Vss_posthoc_NLME'] = p.vc + p.vp
    nca_rows.append(r)
ncad = pd.DataFrame(nca_rows)
ncad.to_csv(OUT / 'rat_nca.csv', index=False)
gm = lambda x: float(np.exp(np.mean(np.log(x))))
nca_summary = {'geometric_mean_CL_NCA': gm(ncad.CL), 'geometric_mean_CL_posthoc': gm(ncad.CL_posthoc_NLME),
               'typical_CL_NLME': theta['cl'],
               'geometric_mean_Vss_NCA': gm(ncad.Vss), 'typical_Vss_NLME': theta['vc'] + theta['vp'],
               'median_pct_AUC_extrapolated': float(ncad.pct_extrap.median()),
               'max_pct_AUC_extrapolated': float(ncad.pct_extrap.max()),
               'rats_with_extrap_gt_20pct': int((ncad.pct_extrap > 20).sum()),
               'median_terminal_half_life_NCA_h': float(ncad.t_half.median()),
               'ratio_CL_NCA_to_posthoc_range': [float((ncad.CL / ncad.CL_posthoc_NLME).min()), float((ncad.CL / ncad.CL_posthoc_NLME).max())]}

# 5. model half-lives for the typical rat
k10 = theta['cl'] / theta['vc']; k12 = theta['q'] / theta['vc']; k21 = theta['q'] / theta['vp']
s_ = k10 + k12 + k21; disc = math.sqrt(s_ ** 2 - 4 * k10 * k21)
alpha, beta = (s_ + disc) / 2, (s_ - disc) / 2
tt = np.linspace(0, 200, 200001)
ctyp = conc_2c(np.array([6.0]), theta['cl'], theta['vc'], theta['q'], theta['vp'], 1.0, 1 / 60)
auc_inf_typ = 1.0 / theta['cl']
t_grid = np.linspace(1/60, 6, 2000)
c_grid = conc_2c(t_grid, theta['cl'], theta['vc'], theta['q'], theta['vp'], 1.0, 1 / 60)
auc06 = float(np.trapezoid(c_grid, t_grid))
terminal = {'alpha_half_life_h': math.log(2) / alpha, 'beta_half_life_h': math.log(2) / beta,
            'sampling_window_h': 6.0, 'windows_in_beta_half_lives': 6.0 / (math.log(2) / beta),
            'typical_fraction_AUCinf_within_0_6h': auc06 / auc_inf_typ}

# 6. exploratory: correlated etas (rho from post hoc EBEs), same estimates
rho = float(stats.pearsonr(post['eta.cl'], post['eta.vc'])[0])
cov_eta = np.array([[om_cl, rho * math.sqrt(om_cl * om_vc)], [rho * math.sqrt(om_cl * om_vc), om_vc]])
Lc = np.linalg.cholesky(cov_eta)
rng2 = np.random.default_rng(1)
ins = bel = abv = 0
for sid, g in obs.groupby('ID'):
    amt = dose.loc[sid, 'AMT']; dur = amt / dose.loc[sid, 'RATE']; t = g.TIME.values
    S = np.empty((NREP, len(t)))
    for r in range(NREP):
        e = Lc @ rng2.normal(size=2)
        f = conc_2c(t, theta['cl'] * math.exp(e[0]), theta['vc'] * math.exp(e[1]), theta['q'], theta['vp'], amt, dur)
        S[r] = f + rng2.normal(size=len(t)) * np.sqrt(add_sd ** 2 + (prop_sd * f) ** 2)
    lo, hi = np.percentile(S, [5, 95], axis=0); dv = g.DV.values
    ins += np.sum((dv >= lo) & (dv <= hi)); bel += np.sum(dv < lo); abv += np.sum(dv > hi)
correlated_eta = {'rho_posthoc_eta_cl_eta_vc': rho, 'rho_p_value': float(stats.pearsonr(post['eta.cl'], post['eta.vc'])[1]),
                  'within_90PI_pct': 100 * ins / n, 'below_5th_pct': 100 * bel / n, 'above_95th_pct': 100 * abv / n,
                  'note': 'Same estimates with the post hoc correlation imposed; a diagnostic hint, not a refit.'}

result = {'candidate': str(BASE), 'nrep': NREP, 'seed': 20260924, 'correlated_eta_npc': correlated_eta,
          'verification': verification, 'conditioning': conditioning, 'npc': npc, 'npde_like': npde_stats,
          'vpc_bins_with_percentile_outside_CI': vpc[[c for c in vpc.columns if c.endswith('outside_CI')]].sum().to_dict(),
          'nca_cross_check': nca_summary, 'terminal_phase': terminal,
          'residual_sd_source': 'fit_summary.txt rounded to 3 significant figures'}
(OUT / 'rat_2C_combined_checks.json').write_text(json.dumps(result, indent=2, default=float))
print(json.dumps(result, indent=2, default=float))
print(vpc.round(3).to_string())
print(ncad.round(3).to_string())
