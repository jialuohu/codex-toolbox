-- Non-mutating probes, including a fixed JavaScript 1+1 expression.
-- The dynamic target avoids loading application terminology
-- while compiling; the event codes come from OmniGraffle 7's scriptSuite.
on run argv
    if (count argv) is not 3 then error "Expected probe, timeout, and application path" number 64
    set probeName to item 1 of argv
    set timeoutSeconds to (item 2 of argv) as integer
    if timeoutSeconds < 1 or timeoutSeconds > 30 then error "Invalid timeout" number 64
    set targetApplication to item 3 of argv
    with timeout of timeoutSeconds seconds
        tell application targetApplication
            if probeName is "version" then
                return version
            else if probeName is "documents" then
                return count of «class docu»
            else if probeName is "professional" then
                return «property OGPR»
            else if probeName is "javascript" then
                return «event OGSSOGEJ» "1+1"
            else
                error "Unsupported probe" number 64
            end if
        end tell
    end timeout
end run
