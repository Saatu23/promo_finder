# Evaluation

| metric | value |
|---|---|
| reference_recall_all_candidates | 1.0 |
| reference_recall_ranked_list | 0.72 |
| reference_mean_best_iou | 0.72 |
| reference_edit_ready_rate | 0.39 |
| baseline_edit_ready_rate | 0.11 |
| baseline_recall | 0.78 |
| baseline_mean_best_iou | 0.5 |
| ranked_promos_in_reference_episodes | 17 |
| of_which_match_a_reference_promo | 13 |
| proposed | 200 |
| failed_rules_first_try | 32 |
| first_try_rule_pass_rate | 0.84 |
| repaired_ok | 105 |
| rule_failures_by_type | {'hook line starts 3.9s into the clip': 2, 'too long': 2, 'hook line 11': 1, 'hook line starts 4.0s into the clip': 1, 'hook line starts 4.3s into the clip': 1, 'hook line starts 5.3s into the clip': 1, 'hook line starts 8.8s into the clip': 2, 'hook line starts 6.0s into the clip': 1, 'hook line starts 8.6s into the clip': 1, 'hook line starts 3.8s into the clip': 1, 'hook line 20': 1, 'hook line starts 3.1s into the clip': 1, 'too short': 10, 'hook line starts 4.2s into the clip': 1, 'hook line starts 3.4s into the clip': 2, 'hook line starts 5.8s into the clip': 1, 'hook line starts 5.2s into the clip': 1, 'hook line starts 4.4s into the clip': 1, 'hook line starts 9.2s into the clip': 1, 'hook line starts 3.5s into the clip': 2, 'hook line starts 11.2s into the clip': 1} |
| judge_vs_cold_viewer | {'n': 218, 'standalone_vs_understood_r': 0.46, 'hook_vs_stopped_r': 0.38, 'mean_abs_gap_standalone': 1.43} |
| ranked_confidence_mix | {'low': 35, 'medium': 5} |
| ranked_spread | {'episodes_covered': 32, 'tropes': ['betrayal', 'comeback', 'danger', 'humiliation', 'protector', 'reveal', 'romance', 'sacrifice', 'villain_scheme']} |
| consistency_top10_found_in_rerun_top20 | 10/10 |

## Reference promos

| id | ep | found by tool | edit-ready cut | in ranked list | best IoU | keyword baseline | note |
|---|---|---|---|---|---|---|---|
| G01a | 1 | yes | yes | yes | 0.93 | no (0.0) | 'You should turn around' -> sister: 'Because he is marrying me.' Altar betrayal reveal. |
| G01b | 1 | yes | yes | no | 1.0 | yes (0.63) | Father won't look at her -> 'You are the daughter people tolerate... I am the daughter they choose.' |
| G03a | 3 | yes | yes | yes | 1.0 | yes (1.0) | 'Guards! Remove her!' -> stranger: 'Take your hands off her', drops a guard, groom: 'He's only one man!' |
| G03b | 3 | yes | yes | yes | 1.0 | yes (0.59) | Stranger defends her, kneels with a ring: 'Lady Juliana... accept my hand.' Ends before her answer. |
| G05a | 5 | yes | no | yes | 0.35 | no (0.2) | Stepmother flings her dead mother's ledger into the mud; sister and ex laugh. |
| G05b | 5 | yes | no | yes | 0.83 | no (0.0) | Father disowns her on the church steps: 'you are dead to the Ashcroft family' -> 'You are my father!' |
| G07a | 7 | yes | no | yes | 0.49 | yes (0.34) | Ex mocks her 'scarred beggar' husband and threatens him -> husband walks up silently, ex freezes. |
| G11a | 11 | yes | no | no | 0.61 | yes (0.73) | 'Your husband stole my gold pocket watch!' -> constable search -> 'Search it.' |
| G11b | 11 | yes | yes | yes | 1.0 | yes (0.72) | Search of the cottage; watch pulled from the husband's coat: 'There it is.' |
| G12a | 12 | yes | no | yes | 0.62 | yes (0.59) | 'I want to see you crawl, sister' - bare-handed in the thorns or he hangs -> 'Tell me where the garden is.' |
| G13a | 13 | yes | no | yes | 0.66 | yes (0.55) | She crawls into frozen blackthorn briars while they mock her and he screams. |
| G18a | 18 | yes | yes | no | 0.96 | yes (0.45) | Burning cottage: she runs back into the fire for her mother's ledger, ceiling falls, he dives on her. |
| G24a | 24 | yes | no | yes | 0.42 | yes (0.77) | 'Then let her suffer.' Noblewoman strikes the 'maid' with a riding crop, sends her to scrub the hearth. |
| G27a | 27 | yes | no | no | 0.38 | no (0.0) | Duchess recognises the ring: 'My lost son wore that ring!' 'What is your husband's name?' -> doors burst open. |
| G27b | 27 | yes | no | yes | 0.58 | yes (0.2) | 'Poison.' Villains twist it: 'She admits she has been giving the Duchess poison!' -> 'Take her.' |
| G41a | 41 | yes | no | yes | 0.61 | yes (0.74) | Chained heroine paraded at the villains' wedding -> cathedral doors explode, armed figures in the smoke. |
| G45a | 45 | yes | yes | yes | 0.93 | yes (0.9) | Duke denounces the villain, proclaims Juliana his wife and Duchess -> 'Juliana?!' |
| G45b | 45 | yes | no | no | 0.62 | yes (0.65) | Proclaimed Duchess -> bishop bursts in: no Crown licence, 'You are not his lawful wife.' |