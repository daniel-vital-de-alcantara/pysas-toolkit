/* Standalone engine smoke test: one output table and two HTML procedure results. */
data work.engine_smoke;
    length label $20;
    input id amount label $;
    datalines;
1 10 first
2 20 second
3 30 third
;
run;

proc print data=work.engine_smoke;
run;

proc means data=work.engine_smoke;
    var amount;
run;
