use framework "Foundation"
use framework "AppKit"
use scripting additions
property appTarget : "/Applications/OmniGraffle.app"

on val(d, k)
    return d's objectForKey:k
end val

on has(d, k)
    return (d's objectForKey:k) is not missing value
end has

on dict(ks, vs)
    return current application's NSMutableDictionary's dictionaryWithObjects:vs forKeys:ks
end dict

on canonical(p)
    if p is missing value or p is "" then return ""
    return ((current application's NSString's stringWithString:p)'s stringByResolvingSymlinksInPath()) as text
end canonical

on documentPath(d)
    using terms from application "/Applications/OmniGraffle.app"
        tell application appTarget
            try
                set nativePath to path of d
                return my canonical(nativePath)
            on error msg number num
                -- Unsaved native documents return an undefined AppleEvent value,
                -- not an empty string or missing value.
                if num is -2753 then return ""
                error msg number num
            end try
        end tell
    end using terms from
end documentPath

on encode(d)
    set raw to current application's NSJSONSerialization's dataWithJSONObject:d options:0 |error|:(missing value)
    if raw is missing value then error "Cannot serialize native response"
    return (current application's NSString's alloc()'s initWithData:raw encoding:(current application's NSUTF8StringEncoding)) as text
end encode

on getDoc(wanted)
    using terms from application "/Applications/OmniGraffle.app"
        tell application appTarget
            set matches to {}
            repeat with d in documents
                if my documentPath(d) is my canonical(wanted) then set end of matches to contents of d
            end repeat
            if (count matches) is not 1 then error "Expected exactly one open document at canonical path"
            return item 1 of matches
        end tell
    end using terms from
end getDoc

on getCanvas(d, wanted)
    using terms from application "/Applications/OmniGraffle.app"
        tell application appTarget
            set matches to every canvas of d whose id is wanted
            if (count matches) is not 1 then error "Ambiguous or missing canvas ID"
            return item 1 of matches
        end tell
    end using terms from
end getCanvas

on graphicsUnder(containerRef, depth)
    if depth > 32 then error "Group depth exceeds inspection limit"
    using terms from application "/Applications/OmniGraffle.app"
        tell application appTarget
            set found to {}
            repeat with g in graphics of containerRef
                set end of found to contents of g
                if class of g is group then set found to found & my graphicsUnder(g, depth + 1)
                if (count found) > 10000 then error "Graphic count exceeds inspection limit"
            end repeat
            return found
        end tell
    end using terms from
end graphicsUnder

on getGraphic(c, wanted)
    set matches to {}
    set gs to my graphicsUnder(c, 0)
    using terms from application "/Applications/OmniGraffle.app"
        tell application appTarget
            repeat with g in gs
                if id of g is wanted then set end of matches to contents of g
            end repeat
        end tell
    end using terms from
    if (count matches) is not 1 then error "Ambiguous or missing graphic ID"
    return item 1 of matches
end getGraphic

on canvasPoints(c)
    using terms from application "/Applications/OmniGraffle.app"
        tell application appTarget
            set wh to canvasSize of c
            if canvas size is measured in pages of c then
                set pageWH to page size of c
                set wh to {(item 1 of wh) * (item 1 of pageWH), (item 2 of wh) * (item 2 of pageWH)}
            end if
            return wh
        end tell
    end using terms from
end canvasPoints

on lineEndpointId(g, endpointName)
    using terms from application "/Applications/OmniGraffle.app"
        tell application appTarget
            try
                if endpointName is "source" then
                    return id of source of g
                else
                    return id of destination of g
                end if
            on error msg number num
                if num is -2753 or num is -1728 then return current application's NSNull's null()
                error msg number num
            end try
        end tell
    end using terms from
end lineEndpointId

on sideMagnetIndex(g, sideName)
    using terms from application "/Applications/OmniGraffle.app"
        tell application appTarget
            set ms to magnets of g
            repeat with i from 1 to count ms
                set p to item i of ms
                set px to (item 1 of p) as real
                set py to (item 2 of p) as real
                if sideName is "top" and px ≥ -0.01 and px ≤ 0.01 and py ≤ -0.49 then return i
                if sideName is "right" and px ≥ 0.49 and py ≥ -0.01 and py ≤ 0.01 then return i
                if sideName is "bottom" and px ≥ -0.01 and px ≤ 0.01 and py ≥ 0.49 then return i
                if sideName is "left" and px ≤ -0.49 and py ≥ -0.01 and py ≤ 0.01 then return i
            end repeat
        end tell
    end using terms from
    error "Endpoint lacks the requested side midpoint magnet"
end sideMagnetIndex

on installSideMagnets(g)
    using terms from application "/Applications/OmniGraffle.app"
        tell application appTarget
            set magnets of g to {{0, 0.5}, {0.5, 0}, {0, -0.5}, {-0.5, 0}}
        end tell
    end using terms from
end installSideMagnets

on sideForMagnet(g, magnetNumber)
    if magnetNumber is 0 then return ""
    repeat with sideName in {"top", "right", "bottom", "left"}
        try
            if my sideMagnetIndex(g, contents of sideName) is magnetNumber then return contents of sideName
        end try
    end repeat
    return ""
end sideForMagnet

on textAlignmentName(enumValue)
    using terms from application "/Applications/OmniGraffle.app"
        if enumValue is left then return "left"
        if enumValue is center then return "center"
        if enumValue is right then return "right"
        if enumValue is justified then return "justified"
        if enumValue is natural then return "natural"
    end using terms from
    error "Unsupported native text alignment"
end textAlignmentName

on verticalAlignmentName(enumValue)
    using terms from application "/Applications/OmniGraffle.app"
        if enumValue is top then return "top"
        if enumValue is center then return "center"
        if enumValue is bottom then return "bottom"
    end using terms from
    error "Unsupported native vertical text alignment"
end verticalAlignmentName

on lineTypeName(enumValue)
    using terms from application "/Applications/OmniGraffle.app"
        if enumValue is straight then return "straight"
        if enumValue is orthogonal then return "orthogonal"
        if enumValue is curved then return "curved"
        if enumValue is bezier then return "bezier"
    end using terms from
    error "Unsupported native line type"
end lineTypeName

on sRGBComponents(rawComponents)
    -- AppleScript NSColor coercion returns calibrated RGB in 16-bit units.
    -- Convert that readback explicitly; request tuples use the existing setter
    -- convention. Saved style-only preservation is verified independently.
    set rgb to rawComponents as list
    if (count rgb) is not 3 then error "Expected three native color components"
    set redValue to ((item 1 of rgb) as real) / 65535
    set greenValue to ((item 2 of rgb) as real) / 65535
    set blueValue to ((item 3 of rgb) as real) / 65535
    set calibratedColor to current application's NSColor's colorWithCalibratedRed:redValue green:greenValue blue:blueValue alpha:1
    set srgbColor to calibratedColor's colorUsingColorSpace:(current application's NSColorSpace's sRGBColorSpace())
    if srgbColor is missing value then error "Native color cannot be converted to sRGB"
    return {(srgbColor's redComponent()) as real, (srgbColor's greenComponent()) as real, (srgbColor's blueComponent()) as real}
end sRGBComponents

on sRGBSetterComponents(rawComponents)
    -- The text-record setter interprets tuples in sRGB. A calibrated readback
    -- tuple cannot be written back directly while preserving the saved color.
    set unitComponents to my sRGBComponents(rawComponents)
    set setterComponents to {}
    repeat with component in unitComponents
        set end of setterComponents to round ((component as real) * 65535)
    end repeat
    return setterComponents
end sRGBSetterComponents

on describeDoc(d)
    set cs to current application's NSMutableArray's array()
    set canvasIDs to {}
    using terms from application "/Applications/OmniGraffle.app"
        tell application appTarget
            if (count canvases of d) > 128 then error "Canvas count exceeds inspection limit"
            repeat with c in canvases of d
                set ci to id of c
                if ci is in canvasIDs then error "Duplicate canvas ID"
                set end of canvasIDs to ci
                set gs to current application's NSMutableArray's array()
                set objectIDs to {}
                repeat with g in my graphicsUnder(c, 0)
                    set readbackGraphicID to 0
                    set readbackField to "identity"
                    try
                    set gi to id of g
                    set readbackGraphicID to gi
                    if gi is in objectIDs then error "Duplicate graphic ID"
                    set end of objectIDs to gi
                    set readbackField to "geometry"
                    set objectRow to my dict({"id", "name", "origin", "size", "kind"}, {gi, user name of g, origin of g, size of g, (class of g) as text})
                    set readbackField to "stroke"
                    objectRow's setObject:(draws stroke of g) forKey:"draws_stroke"
                    objectRow's setObject:(my sRGBComponents(stroke color of g)) forKey:"stroke_rgb"
                    objectRow's setObject:(thickness of g) forKey:"stroke_width"
                    set patternNumber to stroke pattern of g
                    objectRow's setObject:patternNumber forKey:"stroke_pattern_id"
                    if patternNumber is 0 then objectRow's setObject:"solid" forKey:"stroke_pattern"
                    if patternNumber is 1 then objectRow's setObject:"dashed" forKey:"stroke_pattern"
                    if class of g is shape or class of g is solid then
                        set readbackField to "text"
                        set plainLabel to (get «property ctxt» of g) as text
                        objectRow's setObject:plainLabel forKey:"text"
                        if plainLabel is not "" then
                            set readbackField to "font_name"
                            set nativeFont to get «property font» of «property ctxt» of g
                            set readbackField to "font_size"
                            set nativeFontSize to get «property ptsz» of «property ctxt» of g
                            set readbackField to "text_color"
                            set nativeTextColor to get «property colr» of «property ctxt» of g
                            -- OmniGraffle 7.26 exposes paragraph alignment,
                            -- while whole-text alignment returns -1728.
                            set readbackField to "text_align"
                            set nativeAlignment to get «property OTta» of paragraph 1 of «property ctxt» of g
                            objectRow's setObject:nativeFont forKey:"font_name"
                            objectRow's setObject:nativeFontSize forKey:"font_size"
                            objectRow's setObject:(my sRGBComponents(nativeTextColor)) forKey:"text_rgb"
                            objectRow's setObject:(my textAlignmentName(nativeAlignment)) forKey:"text_align"
                        end if
                        set readbackField to "text_valign"
                        set nativePlacement to get text placement of g
                        objectRow's setObject:(my verticalAlignmentName(nativePlacement)) forKey:"text_valign"
                        set readbackField to "text_padding"
                        objectRow's setObject:(side padding of g) forKey:"side_padding"
                        objectRow's setObject:(vertical padding of g) forKey:"vertical_padding"
                        if (side padding of g) is (vertical padding of g) then objectRow's setObject:(side padding of g) forKey:"text_padding"
                        set readbackField to "fill"
                        objectRow's setObject:(my sRGBComponents(fill color of g)) forKey:"fill_rgb"
                        objectRow's setObject:((fill of g) as text) forKey:"fill_type"
                        if class of g is shape then
                            set readbackField to "shape_type"
                            set nativeShapeName to name of g
                            set radius to corner radius of g
                            objectRow's setObject:nativeShapeName forKey:"shape_name"
                            objectRow's setObject:radius forKey:"corner_radius"
                            if nativeShapeName is "Circle" then
                                objectRow's setObject:"ellipse" forKey:"shape_type"
                            else if nativeShapeName is "Rectangle" then
                                if radius > 0 then
                                    objectRow's setObject:"rounded_rectangle" forKey:"shape_type"
                                else
                                    objectRow's setObject:"rectangle" forKey:"shape_type"
                                end if
                            end if
                        end if
                    else if class of g is line then
                        set readbackField to "connector_points"
                        objectRow's setObject:(point list of g) forKey:"points"
                        set readbackField to "connector_endpoints"
                        objectRow's setObject:(my lineEndpointId(g, "source")) forKey:"source_id"
                        objectRow's setObject:(my lineEndpointId(g, "destination")) forKey:"destination_id"
                        set readbackField to "line_type"
                        set nativeLineType to get line type of g
                        objectRow's setObject:(my lineTypeName(nativeLineType)) forKey:"line_type"
                        set readbackField to "line_endings"
                        set headName to (head type of g) as text
                        set tailName to (tail type of g) as text
                        objectRow's setObject:headName forKey:"head_type"
                        objectRow's setObject:tailName forKey:"tail_type"
                        if headName is "FilledArrow" then objectRow's setObject:"filled" forKey:"head_arrow"
                        if tailName is "FilledArrow" then objectRow's setObject:"filled" forKey:"tail_arrow"
                        if headName is "0" or headName is "" then objectRow's setObject:"none" forKey:"head_arrow"
                        if tailName is "0" or tailName is "" then objectRow's setObject:"none" forKey:"tail_arrow"
                        objectRow's setObject:(head magnet of g) forKey:"head_magnet"
                        objectRow's setObject:(tail magnet of g) forKey:"tail_magnet"
                        try
                            set fromSide to my sideForMagnet(source of g, tail magnet of g)
                            if fromSide is not "" then objectRow's setObject:fromSide forKey:"from_side"
                        end try
                        try
                            set toSide to my sideForMagnet(destination of g, head magnet of g)
                            if toSide is not "" then objectRow's setObject:toSide forKey:"to_side"
                        end try
                    end if
                    set readbackField to "record"
                    gs's addObject:objectRow
                    on error ignoredMessage number nativeErrorNumber
                        -- Do not copy native error text: it may include labels.
                        error "Native readback graphic " & readbackGraphicID & " field " & readbackField & " failed (AppleEvent " & nativeErrorNumber & ")" number nativeErrorNumber
                    end try
                end repeat
                cs's addObject:(my dict({"id", "name", "size", "objects"}, {ci, name of c, my canvasPoints(c), gs}))
            end repeat
            return my dict({"id", "path", "modified", "canvases", "color_encoding"}, {id of d, my documentPath(d), modified of d, cs, "srgb_unit"})
        end tell
    end using terms from
end describeDoc

on checkProps(g, p)
    using terms from application "/Applications/OmniGraffle.app"
        tell application appTarget
            if locked of g then error "Target graphic is locked"
            if class of g is group or class of g is line then
                repeat with k in {"text", "font_size", "font_name", "fill", "shape_type", "text_color", "text_align", "text_valign", "text_padding"}
                    if my has(p, contents of k) then error "Text or fill update is unsupported for this graphic class"
                end repeat
            end if
            if class of g is not line then
                repeat with k in {"line_type", "head_arrow", "tail_arrow", "from_side", "to_side"}
                    if my has(p, contents of k) then error "Connector property on a non-line graphic"
                end repeat
            end if
            if class of g is group then
                repeat with k in {"stroke", "stroke_width", "stroke_pattern"}
                    if my has(p, contents of k) then error "Group style update is unsupported"
                end repeat
            end if
            if class of g is solid and my has(p, "shape_type") then error "Shape type on a non-shape solid"
            if class of g is line then
                if my has(p, "from_side") then my sideMagnetIndex(source of g, (my val(p, "from_side")) as text)
                if my has(p, "to_side") then my sideMagnetIndex(destination of g, (my val(p, "to_side")) as text)
            end if
        end tell
    end using terms from
end checkProps

on refreshConnectorPath(g)
    using terms from application "/Applications/OmniGraffle.app"
        tell application appTarget
            -- OmniGraffle may update attached points while retaining its
            -- initial rendered path. Reassign native points through the API,
            -- never write the saved LogicalPath archive ourselves.
            set preservedPoints to point list of g
            set preservedType to line type of g
            set preservedHeadMagnet to head magnet of g
            set preservedTailMagnet to tail magnet of g
            set point list of g to preservedPoints
            if (point list of g) is not preservedPoints then error "Native path refresh changed connector points"
            if (line type of g) is not preservedType then error "Native path refresh changed connector type"
            if (head magnet of g) is not preservedHeadMagnet or (tail magnet of g) is not preservedTailMagnet then error "Native path refresh changed connector attachments"
        end tell
    end using terms from
end refreshConnectorPath

on applyProps(g, p)
    using terms from application "/Applications/OmniGraffle.app"
        tell application appTarget
            set xy to origin of g
            set wh to size of g
            if my has(p, "x") then set item 1 of xy to (my val(p, "x")) as real
            if my has(p, "y") then set item 2 of xy to (my val(p, "y")) as real
            if my has(p, "width") then set item 1 of wh to (my val(p, "width")) as real
            if my has(p, "height") then set item 2 of wh to (my val(p, "height")) as real
            if my has(p, "x") or my has(p, "y") then set origin of g to xy
            if my has(p, "width") or my has(p, "height") then set size of g to wh
            if my has(p, "shape_type") then
                set requestedShape to (my val(p, "shape_type")) as text
                if requestedShape is "ellipse" then
                    set name of g to "Circle"
                    set corner radius of g to 0
                else
                    set name of g to "Rectangle"
                    if requestedShape is "rounded_rectangle" then
                        set corner radius of g to 6
                    else
                        set corner radius of g to 0
                    end if
                end if
            end if
            if my has(p, "text") or my has(p, "font_size") or my has(p, "font_name") or my has(p, "_text_color") or my has(p, "text_align") then
                -- Assigning attributes through `size of text` can change a
                -- transient text object without dirtying/saving the graphic.
                -- Write one complete attributed text record to the graphic.
                set desiredLabel to (get «property ctxt» of g) as text
                set desiredSize to 12
                set desiredFont to "Helvetica"
                set desiredColor to {0, 0, 0}
                set desiredAlign to center
                if desiredLabel is not "" then
                    set desiredSize to get «property ptsz» of «property ctxt» of g
                    set desiredFont to get «property font» of «property ctxt» of g
                    set nativePreservedColor to get «property colr» of «property ctxt» of g
                    set desiredColor to my sRGBSetterComponents(nativePreservedColor)
                    set desiredAlign to get «property OTta» of paragraph 1 of «property ctxt» of g
                end if
                if my has(p, "text") then set desiredLabel to (my val(p, "text")) as text
                if my has(p, "font_size") then set desiredSize to (my val(p, "font_size")) as integer
                if my has(p, "font_name") then set desiredFont to (my val(p, "font_name")) as text
                if my has(p, "_preserved_text_color") then set desiredColor to (my val(p, "_preserved_text_color")) as list
                if my has(p, "_text_color") then set desiredColor to (my val(p, "_text_color")) as list
                if my has(p, "text_align") then
                    set alignName to (my val(p, "text_align")) as text
                    if alignName is "left" then set desiredAlign to left
                    if alignName is "center" then set desiredAlign to center
                    if alignName is "right" then set desiredAlign to right
                end if
                set text of g to {text:desiredLabel, size:desiredSize, font:desiredFont, color:desiredColor, alignment:desiredAlign}
            end if
            if my has(p, "text_valign") then
                set alignName to (my val(p, "text_valign")) as text
                if alignName is "top" then set text placement of g to top
                if alignName is "center" then set text placement of g to center
                if alignName is "bottom" then set text placement of g to bottom
            end if
            if my has(p, "text_padding") then
                set paddingValue to (my val(p, "text_padding")) as integer
                set side padding of g to paddingValue
                set vertical padding of g to paddingValue
            end if
            if my has(p, "_fill") then
                set fill of g to solid fill
                set fill color of g to (my val(p, "_fill")) as list
            end if
            if my has(p, "_stroke") then
                set draws stroke of g to true
                set stroke color of g to (my val(p, "_stroke")) as list
            end if
            if my has(p, "stroke_width") then set thickness of g to (my val(p, "stroke_width")) as real
            if my has(p, "stroke_pattern") then
                if (my val(p, "stroke_pattern")) as text is "solid" then
                    set stroke pattern of g to 0
                else
                    set stroke pattern of g to 1
                end if
            end if
            if my has(p, "line_type") then
                if (my val(p, "line_type")) as text is "orthogonal" then
                    set line type of g to orthogonal
                else
                    set line type of g to straight
                end if
            end if
            if my has(p, "head_arrow") then
                if (my val(p, "head_arrow")) as text is "filled" then
                    set head type of g to "FilledArrow"
                else
                    set head type of g to "0"
                end if
            end if
            if my has(p, "tail_arrow") then
                if (my val(p, "tail_arrow")) as text is "filled" then
                    set tail type of g to "FilledArrow"
                else
                    set tail type of g to "0"
                end if
            end if
            if my has(p, "from_side") then set tail magnet of g to my sideMagnetIndex(source of g, (my val(p, "from_side")) as text)
            if my has(p, "to_side") then set head magnet of g to my sideMagnetIndex(destination of g, (my val(p, "to_side")) as text)
            if class of g is line and (my has(p, "line_type") or my has(p, "from_side") or my has(p, "to_side")) then my refreshConnectorPath(g)
        end tell
    end using terms from
end applyProps

on createDoc(r)
    set mappings to current application's NSMutableDictionary's dictionary()
    set targetPath to (my val(r, "path")) as text
    using terms from application "/Applications/OmniGraffle.app"
        tell application appTarget
            set d to make new document
            set indexN to 0
            repeat with specCanvas in (my val(my val(r, "spec"), "canvases"))
                set indexN to indexN + 1
                if indexN is 1 then
                    set c to canvas 1 of d
                else
                    set c to make new canvas at end of canvases of d
                end if
                set name of c to (my val(specCanvas, "name")) as text
                set adjusts pages of c to false
                set canvas size is measured in pages of c to false
                set canvasSize of c to {(my val(specCanvas, "width")) as real, (my val(specCanvas, "height")) as real}
                set objectKeys to {}
                set nativeRefs to {}
                set preparedMagnetKeys to {}
                set nativeIDs to current application's NSMutableDictionary's dictionary()
                repeat with kindPass in {"shape", "text", "connector", "group"}
                    repeat with o in (my val(specCanvas, "objects"))
                        set kindName to (my val(o, "kind")) as text
                        if kindName is (contents of kindPass) then
                            set keyName to (my val(o, "key")) as text
                            if kindName is "shape" or kindName is "text" then
                                tell c to set g to make new shape with properties {draws shadow:false}
                                set autosizing of g to clip
                                if kindName is "text" then
                                    set fill of g to no fill
                                    set draws stroke of g to false
                                end if
                                my applyProps(g, o)
                            else if kindName is "connector" then
                                set sourceKey to (my val(o, "from")) as text
                                set destinationKey to (my val(o, "to")) as text
                                set a to item (my keyIndex(objectKeys, sourceKey)) of nativeRefs
                                set b to item (my keyIndex(objectKeys, destinationKey)) of nativeRefs
                                tell c to set g to connect a to b
                                set line type of g to straight
                                if my has(o, "_points") then set point list of g to (my val(o, "_points")) as list
                                my applyProps(g, o)
                                if not (my has(o, "line_type") or my has(o, "from_side") or my has(o, "to_side")) then my refreshConnectorPath(g)
                            else
                                set childrenRefs to {}
                                repeat with childKey in (my val(o, "children"))
                                    set end of childrenRefs to item (my keyIndex(objectKeys, childKey as text)) of nativeRefs
                                end repeat
                                set g to assemble childrenRefs
                                my applyProps(g, o)
                            end if
                            set user name of g to keyName
                            set end of objectKeys to keyName
                            set end of nativeRefs to g
                            nativeIDs's setObject:(id of g) forKey:keyName
                        end if
                    end repeat
                    if (contents of kindPass) is "text" then
                        -- Install side magnets before making any connector so a
                        -- later connection cannot move an earlier native line.
                        repeat with o in (my val(specCanvas, "objects"))
                            if (my val(o, "kind")) as text is "connector" then
                                repeat with endpointName in {"from", "to"}
                                    set sideKey to "from_side"
                                    if (contents of endpointName) is "to" then set sideKey to "to_side"
                                    if my has(o, sideKey) then
                                        set endpointKey to (my val(o, contents of endpointName)) as text
                                        if endpointKey is not in preparedMagnetKeys then
                                            set endpointGraphic to item (my keyIndex(objectKeys, endpointKey)) of nativeRefs
                                            my installSideMagnets(endpointGraphic)
                                            set end of preparedMagnetKeys to endpointKey
                                        end if
                                    end if
                                end repeat
                            end if
                        end repeat
                    end if
                end repeat
                mappings's setObject:(my dict({"canvas_id", "objects"}, {id of c, nativeIDs})) forKey:((my val(specCanvas, "key")) as text)
            end repeat
            save d in POSIX file targetPath
            set resultDoc to my describeDoc(d)
            return my dict({"status", "document", "mapping"}, {"ok", resultDoc, mappings})
        end tell
    end using terms from
end createDoc

on keyIndex(keysList, targetKey)
    repeat with i from 1 to count keysList
        if item i of keysList is targetKey then return i
    end repeat
    error "Object key not found"
end keyIndex

on run argv
    try
        set appTarget to item 2 of argv
        set raw to current application's NSData's dataWithContentsOfFile:(item 1 of argv)
        set r to current application's NSJSONSerialization's JSONObjectWithData:raw options:0 |error|:(missing value)
        if r is missing value then error "Invalid JSON request"
        set op to (my val(r, "op")) as text
        using terms from application "/Applications/OmniGraffle.app"
            with timeout of 110 seconds
                tell application appTarget
                    if op is "inventory" then
                        set docs to current application's NSMutableArray's array()
                        if (count documents) > 128 then error "Document count exceeds limit"
                        repeat with d in documents
                            docs's addObject:(my describeDoc(d))
                        end repeat
                        return my encode(my dict({"status", "documents", "version"}, {"ok", docs, version}))
                    end if
                    if op is "create" then return my encode(my createDoc(r))
                    set wantedPath to (my val(r, "path")) as text
                    set d to my getDoc(wantedPath)
                    if op is "inspect" then return my encode(my dict({"status", "document"}, {"ok", my describeDoc(d)}))
                    if op is "save" then
                        save d
                        if modified of d then error "Document remains modified after save"
                        return my encode(my dict({"status", "document"}, {"ok", my describeDoc(d)}))
                    end if
                    if op is "close" then
                        if modified of d and not ((my val(r, "discard")) as boolean) then error "Refusing to discard unsaved changes"
                        close d saving no
                        return my encode(my dict({"status", "path", "closed"}, {"ok", wantedPath, true}))
                    end if
                    if modified of d then error "Refusing operation on document with unsaved changes"
                    if op is "update" then
                        set targetRefs to {}
                        repeat with change in (my val(r, "changes"))
                            set c to my getCanvas(d, (my val(change, "canvas_id")) as integer)
                            set g to my getGraphic(c, (my val(change, "object_id")) as integer)
                            my checkProps(g, my val(change, "set"))
                            set end of targetRefs to g
                        end repeat
                        set i to 0
                        repeat with change in (my val(r, "changes"))
                            set i to i + 1
                            my applyProps(item i of targetRefs, my val(change, "set"))
                        end repeat
                        save d
                        return my encode(my dict({"status", "document"}, {"ok", my describeDoc(d)}))
                    end if
                    if op is "export" then
                        set fileType to (my val(r, "format")) as text
                        set dest to (my val(r, "output")) as text
                        set resolutionRatio to ((my val(r, "dpi")) as real) / 72
                        set selectedCanvas to missing value
                        if my has(r, "canvas_id") then set selectedCanvas to my getCanvas(d, (my val(r, "canvas_id")) as integer)
                        repeat with c in canvases of d
                            if selectedCanvas is missing value or id of c is id of selectedCanvas then
                                set wh to my canvasPoints(c)
                                if item 1 of wh > 14400 or item 2 of wh > 14400 then error "Export canvas exceeds 14400 points"
                                if fileType is "PNG" and ((item 1 of wh) * (item 2 of wh) * resolutionRatio * resolutionRatio > 16000000) then error "Export exceeds 16 million pixels"
                            end if
                        end repeat
                        set opts to {resolution:resolutionRatio, scale:1, includeborder:false}
                        if selectedCanvas is missing value then
                            export d scope entire document as fileType to POSIX file dest with properties opts
                        else
                            set opts to {resolution:resolutionRatio, scale:1, includeborder:false, regionorigin:{0, 0}, regionsize:my canvasPoints(selectedCanvas)}
                            -- Resolve document references individually: OmniGraffle
                            -- rejects a whose-document filter and document.windows.
                            set wins to {}
                            repeat with candidateWindow in windows
                                try
                                    if id of document of candidateWindow is id of d then set end of wins to contents of candidateWindow
                                on error msg number num
                                    -- Inspectors and other utility windows have no document.
                                    if num is not -1728 and num is not -2753 then error msg number num
                                end try
                            end repeat
                            if (count wins) is not 1 then error "Expected one document window for canvas export"
                            set w to item 1 of wins
                            set priorCanvas to canvas of w
                            set canvas of w to selectedCanvas
                            try
                                export d scope current canvas as fileType to POSIX file dest with properties opts
                            on error msg number num
                                set canvas of w to priorCanvas
                                error msg number num
                            end try
                            set canvas of w to priorCanvas
                        end if
                        return my encode(my dict({"status", "output", "format"}, {"ok", dest, fileType}))
                    end if
                    error "Unsupported operation"
                end tell
            end timeout
        end using terms from
    on error msg number num
        return my encode(my dict({"status", "error"}, {"error", my dict({"code", "message", "native_number"}, {"native_error", msg, num})}))
    end try
end run
