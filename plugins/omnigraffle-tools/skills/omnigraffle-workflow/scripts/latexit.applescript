-- Fixed adapters only. The request is JSON data; no source text is evaluated.
use framework "Foundation"
use framework "AppKit"
use scripting additions

on field(r, k)
    set v to r's objectForKey:k
    if v is missing value then error "Missing request field"
    return v
end field

on jsonResult(r)
    set d to current application's NSJSONSerialization's dataWithJSONObject:r options:0 |error|:(missing value)
    return (current application's NSString's alloc()'s initWithData:d encoding:4) as text
end jsonResult

on canonical(p)
    return ((current application's NSString's stringWithString:p)'s stringByResolvingSymlinksInPath()) as text
end canonical

on documentAtPath(appPath, wanted)
    set matches to {}
    using terms from application "/Applications/OmniGraffle.app"
        tell application appPath
            repeat with d in documents
                try
                    if my canonical(path of d) is my canonical(wanted) then set end of matches to contents of d
                on error msg number num
                    if num is not -2753 then error msg number num
                end try
            end repeat
        end tell
    end using terms from
    if (count matches) is not 1 then error "Ambiguous document"
    return item 1 of matches
end documentAtPath

on processFor(pidValue, bundleValue)
    tell application "System Events"
        set candidates to every application process whose unix id is pidValue
        if (count candidates) is not 1 then error "Application process changed"
        set p to item 1 of candidates
        if bundle identifier of p is not bundleValue then error "Application identity changed"
        return p
    end tell
end processFor

on editor(p, titleValue)
    tell application "System Events"
        if (count windows of p) is not 1 then error "Ambiguous editor or unexpected dialog"
        set w to window 1 of p
        if name of w is not titleValue then error "Editor changed"
        if (count sheets of w) is not 0 then error "Unexpected sheet"
        return w
    end tell
end editor

on textFields(p, w)
    tell application "System Events"
        set contentsList to entire contents of w
        set areas to {}
        repeat with el in contentsList
            if class of el is text area then set end of areas to contents of el
        end repeat
        if (count areas) is 1 then
            set expectedTitle to name of w
            set mi to menu item "Show preamble" of menu "LaTeX" of menu bar item "LaTeX" of menu bar 1 of p
            if not enabled of mi then error "Cannot show preamble"
            click mi
            repeat 20 times
                set w to my editor(p, expectedTitle)
                set contentsList to entire contents of w
                set areas to {}
                repeat with el in contentsList
                    if class of el is text area then set end of areas to contents of el
                end repeat
                if (count areas) is 2 then exit repeat
                delay 0.05
            end repeat
        end if
        if (count areas) is not 2 then error "Unsupported editor text structure"
        return areas
    end tell
end textFields

on readEquation(p, w)
    set areas to my textFields(p, w)
    set chosenMode to ""
    set sizeValue to missing value
    tell application "System Events"
        set elementsList to entire contents of w
        repeat with el in elementsList
            if class of el is radio button and value of el is 1 then
                set labelValue to description of el
                if labelValue is "Display" then set chosenMode to "display"
                if labelValue is "Inline" then set chosenMode to "inline"
                if labelValue is "Align" then set chosenMode to "align"
                if labelValue is "Text" then set chosenMode to "text"
            end if
            if class of el is text field then
                set candidate to value of el as text
                if candidate ends with " pt" then set sizeValue to candidate
            end if
        end repeat
        if chosenMode is "" or sizeValue is missing value then error "Unsupported equation controls"
        set bodyValue to value of item 2 of areas as text
        set preambleValue to value of item 1 of areas as text
    end tell
    set numericSize to (current application's NSString's stringWithString:sizeValue)'s doubleValue() as real
    return current application's NSDictionary's dictionaryWithDictionary:{source:bodyValue, preamble:preambleValue, mode:chosenMode, font_size:numericSize}
end readEquation

on requireLinkBack(w)
    set activeCount to 0
    tell application "System Events"
        set elementsList to entire contents of w
        repeat with el in elementsList
            try
                set helpValue to value of attribute "AXHelp" of el as text
                ignoring case
                    if helpValue contains "LinkBack" then
                        set stateValue to value of el
                        if stateValue is 1 or stateValue is "on" then set activeCount to activeCount + 1
                    end if
                end ignoring
            end try
        end repeat
    end tell
    if activeCount is not 1 then error "No uniquely active LinkBack connection"
end requireLinkBack

on namedButton(w, labelValue)
    set matches to {}
    tell application "System Events"
        set elementsList to entire contents of w
        repeat with el in elementsList
            if class of el is button then
                if name of el is labelValue then set end of matches to contents of el
            end if
        end repeat
    end tell
    if (count matches) > 1 then error "Ambiguous editor button"
    if (count matches) is 0 then return missing value
    return item 1 of matches
end namedButton

on setEditorText(p, w, areaValue, textValue, expectedCount)
    set pb to current application's NSPasteboard's generalPasteboard()
    if (pb's changeCount() as integer) is not expectedCount then error "Clipboard changed before text entry"
    tell application "System Events" to set originalText to value of areaValue as text
    if originalText is textValue then return expectedCount
    -- Address the verified text area directly. LaTeXiT's Paste action can
    -- leave selected editor text unchanged despite reporting success.
    tell application "System Events"
        set frontmost of p to true
        set value of attribute "AXFocused" of areaValue to true
        if not (value of attribute "AXFocused" of areaValue) then error "Equation text focus unavailable"
        keystroke "a" using command down
        if not (value of attribute "AXFocused" of areaValue) then error "Equation text focus changed"
        set value of attribute "AXSelectedText" of areaValue to textValue
    end tell
    repeat 20 times
        tell application "System Events" to set actualText to value of areaValue as text
        if actualText is textValue then exit repeat
        delay 0.05
    end repeat
    if actualText is not textValue then error "Equation text does not match request (requested " & (length of textValue) & ", read " & (length of actualText) & " characters)"
    if (pb's changeCount() as integer) is not expectedCount then error "Clipboard changed during text entry"
    return expectedCount
end setEditorText

on run argv
    if (count argv) is not 2 then error "Expected phase and JSON file"
    set phase to item 1 of argv
    set rawData to current application's NSData's dataWithContentsOfFile:(item 2 of argv)
    set r to current application's NSJSONSerialization's JSONObjectWithData:rawData options:0 |error|:(missing value)
    if r is missing value then error "Invalid JSON"
    set op to my field(r, "op") as text
    set lp to my processFor((my field(r, "latexit_pid")) as integer, "fr.chachatelier.pierre.LaTeXiT")
    set gp to my processFor((my field(r, "omni_pid")) as integer, "com.omnigroup.OmniGraffle7")
    set omniPath to my field(r, "omni_app") as text
    with timeout of 15 seconds
        if phase is "preflight" then
            tell application "System Events"
                if not UI elements enabled then error "Accessibility unavailable"
                if (count windows of lp) is not 0 then error "Close existing LaTeXiT windows first"
            end tell
            return my jsonResult({status:"ok"})
        end if
        if phase is "begin" then
            tell application "System Events"
                if (count windows of lp) is not 0 then error "Existing LaTeXiT editor"
            end tell
            if op is "equation-source" or op is "equation-update" then
                set expectedPath to my field(r, "path") as text
                set canvasID to my field(r, "canvas_id") as integer
                set objectID to my field(r, "object_id") as integer
                using terms from application "/Applications/OmniGraffle.app"
                    tell application omniPath
                        set d to my documentAtPath(omniPath, expectedPath)
                        if modified of d then error "Unsaved working document"
                        if id of document of front window is not id of d then error "Wrong front document"
                        set cs to every canvas of d whose id is canvasID
                        if (count cs) is not 1 then error "Ambiguous canvas"
                        set c to item 1 of cs
                        set gs to every graphic of c whose id is objectID
                        if (count gs) is not 1 then error "Ambiguous graphic"
                        set canvas of front window to c
                        set selection of front window to gs
                        set selectedObjects to selection of front window
                        if (count selectedObjects) is not 1 then error "Selection mismatch"
                        if id of item 1 of selectedObjects is not objectID then error "Selection mismatch"
                    end tell
                end using terms from
                tell application "System Events"
                    set frontmost of gp to true
                    set em to menu "Edit" of menu bar item "Edit" of menu bar 1 of gp
                    if exists menu item "Edit in LaTeXiT" of em then
                        set mi to menu item "Edit in LaTeXiT" of em
                    else
                        set mi to menu item "Refresh in LaTeXiT" of em
                    end if
                    if not enabled of mi then error "LinkBack action unavailable"
                    click mi
                end tell
            else
                set texInput to my field(r, "tex_input") as text
                set latexitPath to my field(r, "latexit_app") as text
                tell application latexitPath to open POSIX file texInput
            end if
            repeat 40 times
                tell application "System Events"
                    if (count windows of lp) is 1 then exit repeat
                end tell
                delay 0.1
            end repeat
            tell application "System Events"
                if (count windows of lp) is not 1 then error "Editor did not open"
                set titleValue to name of window 1 of lp
                if op is "equation-source" or op is "equation-update" then
                    if titleValue is not "Equation linked with another application" then error "LinkBack editor not identified"
                end if
            end tell
            return my jsonResult({status:"ok", editor_title:titleValue})
        end if
        set titleValue to my field(r, "editor_title") as text
        set w to my editor(lp, titleValue)
        if phase is not "close" and (op is "equation-source" or op is "equation-update") then my requireLinkBack(w)
        if phase is "read" then return my jsonResult({status:"ok", equation:my readEquation(lp, w)})
        if phase is "close" then
            tell application "System Events"
                set buttonsFound to every button of w whose subrole is "AXCloseButton"
                if (count buttonsFound) is not 1 then error "Cannot identify close control"
                click item 1 of buttonsFound
                if (count windows of lp) is not 0 then error "Editor not closed; inspect dialog"
            end tell
            return my jsonResult({status:"ok"})
        end if
        if phase is "render" then
            set eq to my field(r, "equation")
            set requestedMode to my field(eq, "mode") as text
            tell application "System Events"
                set frontmost of lp to true
                set fontControls to {}
                set modeControls to {}
                set elementsList to entire contents of w
                repeat with el in elementsList
                    if class of el is text field then
                        if (value of el as text) ends with " pt" then
                            set end of fontControls to contents of el
                        end if
                    end if
                    if class of el is radio button then
                        ignoring case
                            if description of el is requestedMode then
                                set end of modeControls to contents of el
                            end if
                        end ignoring
                    end if
                end repeat
                if (count fontControls) is not 1 or (count modeControls) is not 1 then error "Ambiguous equation controls"
                -- Mode selection can replace editor defaults. Set it before equation text.
                click item 1 of modeControls
                set value of attribute "AXFocused" of item 1 of fontControls to true
                if not (value of attribute "AXFocused" of item 1 of fontControls) then error "Font field focus unavailable"
                set value of item 1 of fontControls to (my field(eq, "font_size") as text)
                -- End the field edit so the formatter commits the scalar point size.
                key code 48
            end tell
            set w to my editor(lp, titleValue)
            set areas to my textFields(lp, w)
            set renderControl to my namedButton(w, "LaTeX it!")
            if renderControl is missing value then error "Render control missing"
            set clipboardCount to my field(r, "clipboard_count") as integer
            set clipboardCount to my setEditorText(lp, w, item 1 of areas, my field(eq, "preamble") as text, clipboardCount)
            set areas to my textFields(lp, w)
            set clipboardCount to my setEditorText(lp, w, item 2 of areas, my field(eq, "source") as text, clipboardCount)
            set renderControl to my namedButton(w, "LaTeX it!")
            if renderControl is missing value then error "Render control disappeared"
            tell application "System Events"
                if not enabled of renderControl then error "Render control disabled"
                click renderControl
            end tell
            set renderIdle to false
            delay 0.2
            repeat 100 times
                try
                    set w to my editor(lp, titleValue)
                    set renderControl to my namedButton(w, "LaTeX it!")
                    if renderControl is not missing value then
                        tell application "System Events" to set renderIdle to enabled of renderControl
                        if renderIdle then exit repeat
                    end if
                on error errorMessage number errorNumber
                    -- Stop becomes LaTeX it! while enumerating the AX snapshot.
                    -- Refresh this read only; never replay the render click.
                    if errorNumber is not -1728 then error errorMessage number errorNumber
                    set renderIdle to false
                end try
                delay 0.1
            end repeat
            if not renderIdle then error "Rendering still active"
            tell application "System Events"
                set elementsList to entire contents of w
                repeat with el in elementsList
                    if class of el is table then
                        if (count rows of el) > 0 then return my jsonResult({status:"invalid_tex", change_count:clipboardCount})
                    end if
                end repeat
            end tell
            return my jsonResult({status:"ok", equation:my readEquation(lp, w), change_count:clipboardCount})
        end if
        if phase is "copy" then
            set pb to current application's NSPasteboard's generalPasteboard()
            if (pb's changeCount() as integer) is not (my field(r, "clipboard_count") as integer) then error "Clipboard changed before copy"
            tell application "System Events"
                set frontmost of lp to true
                click menu item "PDF" of menu 1 of menu item "Copy the image as" of menu "Edit" of menu bar item "Edit" of menu bar 1 of lp
            end tell
            repeat 30 times
                set pdfData to pb's dataForType:"com.adobe.pdf"
                set linkData to pb's dataForType:"LinkBackData"
                if (pb's changeCount() as integer) is not (my field(r, "clipboard_count") as integer) and pdfData is not missing value and linkData is not missing value then
                    if (pdfData's |length|() as integer) > 5 and (linkData's |length|() as integer) > 0 then exit repeat
                end if
                delay 0.1
            end repeat
            if (pb's changeCount() as integer) is (my field(r, "clipboard_count") as integer) then error "Copy did not change clipboard"
            if pdfData is missing value or linkData is missing value then error "Copy did not provide PDF and LinkBack data"
            return my jsonResult({status:"ok", change_count:(pb's changeCount() as integer)})
        end if
        if phase is "paste" then
            set pb to current application's NSPasteboard's generalPasteboard()
            if (pb's changeCount() as integer) is not (my field(r, "clipboard_count") as integer) then error "Clipboard changed before paste"
            set expectedPath to my field(r, "path") as text
            set canvasID to my field(r, "canvas_id") as integer
            using terms from application "/Applications/OmniGraffle.app"
                tell application omniPath
                    set d to my documentAtPath(omniPath, expectedPath)
                    if modified of d then error "Unsaved working document"
                    if id of document of front window is not id of d then error "Wrong front document"
                    set cs to every canvas of d whose id is canvasID
                    if (count cs) is not 1 then error "Ambiguous canvas"
                    set c to item 1 of cs
                    set canvas of front window to c
                    set priorIDs to id of every graphic of c
                end tell
            end using terms from
            tell application "System Events"
                set frontmost of gp to true
                click menu item "Paste" of menu "Edit" of menu bar item "Edit" of menu bar 1 of gp
            end tell
            using terms from application "/Applications/OmniGraffle.app"
                tell application omniPath
                    if my canonical(path of document of front window) is not my canonical(expectedPath) then error "Document changed after paste"
                    set selectedObjects to selection of front window
                    if (count selectedObjects) is not 1 then error "Ambiguous pasted equation"
                    set g to item 1 of selectedObjects
                    if id of g is in priorIDs then error "No new equation selected"
                    if (count graphics of c) is not ((count priorIDs) + 1) then error "Unexpected insertion result"
                    set user name of g to my field(r, "key") as text
                    set origin of g to {my field(r, "x") as real, my field(r, "y") as real}
                    set newID to id of g
                end tell
            end using terms from
            return my jsonResult({status:"ok", object_id:newID, canvas_id:canvasID})
        end if
        error "Unsupported phase"
    end timeout
end run
