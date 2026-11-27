### Formaldehyde

**Release the fit only.** Across the six standards (Formaldehyde.csv, lines 2–7), the fitted equation is optical density = 0.005086 + 0.876286 × carbohydrate volume in mL, with R² = 0.999047. The lowest and highest standards give optical densities of 0.086 at 0.1 mL and 0.782 at 0.9 mL. The proposed reading of 0.800 exceeds the upper standard. Using the fit there would require extrapolation, and the high R² alone does not validate quantification at that reading. Withhold the unknown result pending an in-range measurement or a validated extension of the curve. Reporting mg/L would also require a documented conversion from carbohydrate volume to mass concentration.

### ChickWeight

**Revise the follow-up count and gain.** Diet 1 had 20 chicks at birth and 16 with day-21 weights (ChickWeight.csv, lines 2–221). Chicks 8, 15, 16 and 18 were last weighed on days 20, 14, 12 and 2, respectively. The quoted 136.35 g is the difference between the day-21 mean for 16 chicks (177.75 g) and the birth mean for all 20 (41.40 g). Matching both weights by chick ID gives a birth mean of 41.5625 g for the same 16 chicks. Their mean individual gain was 136.1875 g, or **136.19 g**. The mean gain for all 20 cannot be determined from the recorded endpoints.

### attenu

**Revise the event count, mean and station claim.** The 182 acceleration readings come from 23 earthquake IDs, with 1 to 38 readings per event (attenu.csv, lines 2–183). The mean over readings is 0.1542 g, which gives more weight to earthquakes with more recordings. Averaging readings within each event and then taking the mean of the 23 event means gives **0.1329 g** with equal weight per earthquake. The IDs distinguish the events but do not establish statistical independence. Station IDs are recorded for 166 readings. The other 16 have blank station fields on CSV lines 80, 82, 95, 97, 100, 108–109, 115, 117, 119, 124, 127, 129, 156–157 and 161. Those readings retain their event IDs and acceleration values and are included in both means.
