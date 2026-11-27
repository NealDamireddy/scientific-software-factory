# Records and study materials

All three CSVs preserve the published columns, observations and ordering of the R datasets package, version 4.5.2. Only the CSV serialization is new. Source-row addresses count the header as line 1. The draft release claims, including the 0.800 unknown reading, were written for this evaluation. They are not findings or samples supplied by the original studies.

| Record | Data origin and dictionary |
| --- | --- |
| Formaldehyde | Bennett and Franklin, *Statistical Analysis in Chemistry and the Chemical Industry* (1954). [R dataset record](https://stat.ethz.ch/R-manual/R-devel/library/datasets/html/Formaldehyde.html) |
| ChickWeight | Crowder and Hand, *Analysis of Repeated Measures* (1990), example 5.3, and Hand and Crowder, *Practical Longitudinal Data Analysis* (1996), table A.2. [R dataset record](https://stat.ethz.ch/R-manual/R-devel/library/datasets/html/ChickWeight.html) |
| attenu | Joyner, Boore and Porcella, 1981. [Original USGS report](https://pubs.usgs.gov/of/1981/0365/) and [R dataset record](https://stat.ethz.ch/R-manual/R-devel/library/datasets/html/attenu.html) |

To verify this archived packet, run `shasum -c manifest.sha256` and `python3 scoring/verify.py` from this directory. To re-export the records from an installation of R with the matching datasets package, run `Rscript --vanilla packet-source.R`.
