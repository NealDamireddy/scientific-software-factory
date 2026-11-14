"""Registered changes with independent acceptance criteria."""
import statistics

EXTENSION = "fit-quality"


def covers_behavior(order, project):
    requirement = project.get("extensions", {}).get(EXTENSION)
    behavior = project["contract"]
    if EXTENSION in order["acceptance"] and requirement:
        behavior += " " + requirement
    return order["behavior"] == behavior


def check_fit_quality(output, rows):
    # Classical unweighted R-squared in a simple regression with an intercept equals r^2.
    # Use covariance-based correlation as an oracle independent of the app's RSS implementation.
    expected = statistics.correlation([1/t for t,_ in rows],[y for _,y in rows])**2
    actual = output.get("r_squared")
    return {"field":"r_squared","expected":expected,"actual":actual,"tolerance":1e-9,
            "pass":type(actual) in (float,int) and abs(actual-expected)<=1e-9}


def noisy_series():
    return b"temperature_K,intensity_au\n50,2.61\n82,1.6\n120,1.50\n160,0.98\n220,0.71\n300,0.70\n"
