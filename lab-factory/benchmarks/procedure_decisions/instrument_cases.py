"""Fixed inputs and independent expectations for a three-instrument comparison."""

def doc(key, kind, title, source, text):
    return dict(id=key, kind=kind, title=title, source=source, text=text)


LOCAL = "Simulated metrology laboratory record"
DOCS = [
    doc("balance-guide", "manual", "OHAUS Scout SPX operating capability notes",
        "https://europe.ohaus.com/en-ap/scoutspx-3",
        "The Scout SPX provides a weighing mode, a tare function and a stability indicator."),
    doc("light-guide", "manual", "Extech LT300 illuminance capability notes",
        "https://www.flir.com/globalassets/imported-assets/document/extech-catalog-41.pdf",
        "The LT300 measures illuminance and can report readings in lux or foot-candles."),
    doc("logger-guide", "manual", "Testo 174 T operating capability notes",
        "https://www.testo.com/en-UK/p/0572-1740-02",
        "The 174 T records temperature over time. Its configurable measuring rate ranges from 1 min to 24 h."),
    doc("retired-job", "note", "Retired warehouse lighting and temperature survey", LOCAL,
        "The warehouse lighting inspection used only the center position. The old warehouse temperature survey "
        "sampled every 5 min. These settings belong to the retired warehouse job."),
    doc("consumables", "note", "Replacement packaging inventory", LOCAL,
        "Spare instrument cases, paper sleeves and shipping labels are stored together."),
]

CASES = {
    "balance": dict(model="Scout SPX", device="balance-1", commands=["weigh"], setting=None,
        goal="Compare the net masses of the two delivered aluminum coupons.",
        bench="Coupons A and B are separately labeled. The verified Scout SPX is level and ready in weighing mode "
              "with grams selected. Use the same clean dish, tare it empty before each coupon, and accept one "
              "stable net mass reading per coupon. The weigh action acquires the displayed mass.",
        brief="Record the net mass in grams for each coupon. Identify the heavier coupon or report a tie.",
        expected="in_review", guide="balance-guide"),
    "illuminance": dict(model="LT300", device="lux-1", commands=["read_lux"], setting=None,
        goal="Compare the illuminance delivered by lamps A and B in the test booth.",
        bench="The verified LT300 is ready in lux mode. Lamps A and B are energized separately in the darkened "
              "booth after warm-up. A jig fixes sensor height and orientation. Its two available measurement "
              "positions are center and edge. Take one stable lux reading per lamp at the same selected position.",
        brief="The project compares a single measurement position shared by the lamps. Both center and edge "
              "are feasible study designs. Record each lamp's lux and identify the brighter lamp or a tie.",
        expected="researcher_choice", guide="light-guide", answer="Use the edge position for both lamps.",
        question_terms=(("center", "centre"), ("edge",))),
    "temperature": dict(model="174 T", device="logger-1", commands=["record_temperature"], setting="interval",
        goal="Compare temperature variation in storage enclosures A and B over their scheduled holds.",
        bench="The verified 174 T is ready in Celsius. Matched holds are scheduled sequentially so the same "
              "logger occupies the marked rack position in each empty enclosure. Start and stop on the schedule "
              "boundaries. Use one complete trace per enclosure; repeat any hold with a gap in its trace.",
        brief="Use the project-authorized sampling interval for both holds. Report the temperature range "
              "(maximum minus minimum) in each enclosure, and identify the enclosure with the smaller range or a tie.",
        expected="missing_method_detail", guide="logger-guide", answer="The project authorizes a 2 min sampling interval for both holds.",
        question_terms=(("interval", "rate", "frequency", "how often", "cadence", "period"),)),
}


def request(case):
    c = CASES[case]
    instrument = {"id": c["device"], "name": c["model"], "model": c["model"], "firmware": "not recorded",
                  "parameters": [], "commands": [{"name": cmd, "required": []} for cmd in c["commands"]]}
    if c["setting"]:
        instrument["parameters"] = [{"name": "interval", "unit": "min", "minimum": 1, "maximum": 1440}]
        instrument["commands"][0]["required"] = ["interval"]
    return {"request_id": "intake", "lab": {"id": "metrology", "name": "Teaching metrology bench",
            "instruments": [instrument], "documents": DOCS + [doc("bench", "note", "Active bench inventory", LOCAL, c["bench"])]},
            "experiment": {"id": case, "title": c["goal"], "goal": c["goal"], "lab_id": "metrology",
            "instrument_ids": [c["device"]], "documents": [doc("brief", "note", "Current project design", LOCAL, c["brief"])]}}
