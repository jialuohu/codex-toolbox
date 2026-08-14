use AppleScript version "2.4"
use framework "Foundation"
use scripting additions

property NSMutableArray : a reference to current application's NSMutableArray
property NSMutableDictionary : a reference to current application's NSMutableDictionary

on run argv
    try
        if (count of argv) is not 1 then error "invalid request" number 9201
        set requestObject to my readJSON(item 1 of argv)
        set requestVersion to my integerValue(requestObject, "version", 0)
        if requestVersion is not 1 then error "unsupported request" number 9201
        set actionName to my textValue(requestObject, "action", "")
        set paramsObject to requestObject's objectForKey:"params"
        if paramsObject is missing value then set paramsObject to NSMutableDictionary's dictionary()

        if actionName is "health" then
            set resultObject to my healthAction()
        else if actionName is "list_accounts" then
            set resultObject to my listAccountsAction()
        else if actionName is "list_mailboxes" then
            set resultObject to my listMailboxesAction(paramsObject)
        else if actionName is "list_messages" then
            set resultObject to my listMessagesAction(paramsObject)
        else if actionName is "get_message" then
            set resultObject to my getMessageAction(paramsObject)
        else if actionName is "find_message" then
            set resultObject to my findMessageAction(paramsObject)
        else if actionName is "list_attachments" then
            set resultObject to my listAttachmentsAction(paramsObject)
        else if actionName is "fetch_attachment" then
            set resultObject to my fetchAttachmentAction(paramsObject)
        else if actionName is "create_draft" then
            set resultObject to my createDraftAction(paramsObject)
        else if actionName is "mutate_message" then
            set resultObject to my mutateMessageAction(paramsObject)
        else
            error "unsupported action" number 9201
        end if
        my emitEnvelope(true, resultObject, missing value, missing value)
    on error errorMessage number errorNumber
        if errorNumber is -1743 then
            my emitEnvelope(false, missing value, "permission_required", "Mail automation permission is required")
        else if errorNumber is 9202 then
            my emitEnvelope(false, missing value, "not_found", errorMessage)
        else if errorNumber is 9203 then
            my emitEnvelope(false, missing value, "ambiguous", errorMessage)
        else if errorNumber is 9201 then
            my emitEnvelope(false, missing value, "validation_error", errorMessage)
        else
            my emitEnvelope(false, missing value, "bridge_error", "Mail operation failed")
        end if
    end try
end run

on readJSON(posixPath)
    set fileData to current application's NSData's dataWithContentsOfFile:posixPath
    if fileData is missing value then error "invalid request" number 9201
    set {jsonObject, jsonError} to current application's NSJSONSerialization's JSONObjectWithData:fileData options:0 |error|:(reference)
    if jsonObject is missing value then error "invalid request" number 9201
    return jsonObject
end readJSON

on emitEnvelope(isOK, dataObject, errorCode, errorMessage)
    set envelope to NSMutableDictionary's dictionary()
    envelope's setObject:isOK forKey:"ok"
    if isOK then
        envelope's setObject:dataObject forKey:"data"
    else
        set errorObject to NSMutableDictionary's dictionary()
        errorObject's setObject:errorCode forKey:"code"
        errorObject's setObject:errorMessage forKey:"message"
        envelope's setObject:errorObject forKey:"error"
    end if
    set {jsonData, jsonError} to current application's NSJSONSerialization's dataWithJSONObject:envelope options:0 |error|:(reference)
    if jsonData is missing value then error "serialization failed"
    set jsonText to current application's NSString's alloc()'s initWithData:jsonData encoding:(current application's NSUTF8StringEncoding)
    return jsonText as text
end emitEnvelope

on textValue(dictionaryObject, keyName, defaultValue)
    set valueObject to dictionaryObject's objectForKey:keyName
    if valueObject is missing value or valueObject is (current application's NSNull's |null|()) then return defaultValue
    return valueObject as text
end textValue

on integerValue(dictionaryObject, keyName, defaultValue)
    set valueObject to dictionaryObject's objectForKey:keyName
    if valueObject is missing value or valueObject is (current application's NSNull's |null|()) then return defaultValue
    return valueObject as integer
end integerValue

on booleanValue(dictionaryObject, keyName, defaultValue)
    set valueObject to dictionaryObject's objectForKey:keyName
    if valueObject is missing value or valueObject is (current application's NSNull's |null|()) then return defaultValue
    return valueObject as boolean
end booleanValue

on arrayValue(dictionaryObject, keyName)
    set valueObject to dictionaryObject's objectForKey:keyName
    if valueObject is missing value or valueObject is (current application's NSNull's |null|()) then return NSMutableArray's array()
    return valueObject
end arrayValue

on putNullableText(dictionaryObject, keyName, rawValue)
    if rawValue is missing value then
        dictionaryObject's setObject:(current application's NSNull's |null|()) forKey:keyName
    else
        try
            set stringValue to rawValue as text
            if stringValue is "" then
                dictionaryObject's setObject:(current application's NSNull's |null|()) forKey:keyName
            else
                dictionaryObject's setObject:stringValue forKey:keyName
            end if
        on error
            dictionaryObject's setObject:(current application's NSNull's |null|()) forKey:keyName
        end try
    end if
end putNullableText

on isoDate(dateValue)
    if dateValue is missing value then return missing value
    try
        set dateFormatter to current application's NSDateFormatter's alloc()'s init()
        dateFormatter's setLocale:(current application's NSLocale's localeWithLocaleIdentifier:"en_US_POSIX")
        dateFormatter's setDateFormat:"yyyy-MM-dd'T'HH:mm:ssZZZZZ"
        return (dateFormatter's stringFromDate:dateValue) as text
    on error
        return dateValue as text
    end try
end isoDate

on healthAction()
    tell application "Mail"
        set mailVersion to version as text
        set runningState to running
    end tell
    set resultObject to NSMutableDictionary's dictionary()
    resultObject's setObject:mailVersion forKey:"mail_version"
    resultObject's setObject:runningState forKey:"running"
    return resultObject
end healthAction

on listAccountsAction()
    set rows to NSMutableArray's array()
    tell application "Mail"
        repeat with accountObject in every account
            if enabled of accountObject then
                set rowObject to NSMutableDictionary's dictionary()
                rowObject's setObject:(id of accountObject as text) forKey:"account_id"
                rowObject's setObject:(name of accountObject as text) forKey:"name"
                try
                    rowObject's setObject:(account type of accountObject as text) forKey:"account_type"
                on error
                    rowObject's setObject:"unknown" forKey:"account_type"
                end try
                set addressRows to NSMutableArray's array()
                set configuredAddresses to get email addresses of accountObject
                repeat with addressValue in configuredAddresses
                    set addressText to get addressValue
                    addressRows's addObject:(addressText as text)
                end repeat
                rowObject's setObject:addressRows forKey:"email_addresses"
                rows's addObject:rowObject
            end if
        end repeat
    end tell
    set resultObject to NSMutableDictionary's dictionary()
    resultObject's setObject:rows forKey:"accounts"
    return resultObject
end listAccountsAction

on resolveAccount(accountID)
    tell application "Mail"
        set matches to every account whose id is accountID and enabled is true
    end tell
    if (count of matches) is 0 then error "Account is unavailable" number 9202
    if (count of matches) is not 1 then error "Account identity is ambiguous" number 9203
    return item 1 of matches
end resolveAccount

on resolveMailbox(accountObject, pathArray)
    tell application "Mail" to set candidates to every mailbox of accountObject
    set segmentCount to pathArray's |count|()
    if segmentCount is 0 then error "Mailbox path is empty" number 9201
    repeat with segmentIndex from 0 to (segmentCount - 1)
        set segmentName to (pathArray's objectAtIndex:segmentIndex) as text
        set matches to {}
        tell application "Mail"
            repeat with candidateObject in candidates
                if (name of candidateObject as text) is segmentName then set end of matches to candidateObject
            end repeat
        end tell
        if (count of matches) is 0 then error "Mailbox is unavailable" number 9202
        if (count of matches) is not 1 then error "Mailbox identity is ambiguous" number 9203
        set selectedMailbox to item 1 of matches
        if segmentIndex < (segmentCount - 1) then
            tell application "Mail" to set candidates to every mailbox of selectedMailbox
        end if
    end repeat
    return selectedMailbox
end resolveMailbox

on appendMailboxes(mailboxObjects, parentPath, outputRows)
    tell application "Mail"
        repeat with mailboxObject in mailboxObjects
            set mailboxName to name of mailboxObject as text
            set currentPath to NSMutableArray's arrayWithArray:parentPath
            currentPath's addObject:mailboxName
            set rowObject to NSMutableDictionary's dictionary()
            rowObject's setObject:currentPath forKey:"path"
            rowObject's setObject:mailboxName forKey:"name"
            try
                rowObject's setObject:(unread count of mailboxObject as integer) forKey:"unread_count"
            on error
                rowObject's setObject:0 forKey:"unread_count"
            end try
            try
                rowObject's setObject:(count of messages of mailboxObject) forKey:"message_count"
            on error
                rowObject's setObject:0 forKey:"message_count"
            end try
            outputRows's addObject:rowObject
            set childMailboxes to every mailbox of mailboxObject
            if (count of childMailboxes) > 0 then my appendMailboxes(childMailboxes, currentPath, outputRows)
        end repeat
    end tell
end appendMailboxes

on listMailboxesAction(paramsObject)
    set accountObject to my resolveAccount(my textValue(paramsObject, "account_id", ""))
    set rows to NSMutableArray's array()
    tell application "Mail" to set topMailboxes to every mailbox of accountObject
    my appendMailboxes(topMailboxes, NSMutableArray's array(), rows)
    set resultObject to NSMutableDictionary's dictionary()
    resultObject's setObject:rows forKey:"mailboxes"
    return resultObject
end listMailboxesAction

on recipientAddresses(recipientObjects)
    set rows to NSMutableArray's array()
    tell application "Mail"
        repeat with recipientObject in recipientObjects
            try
                rows's addObject:(address of recipientObject as text)
            end try
        end repeat
    end tell
    return rows
end recipientAddresses

on messageRecord(messageObject, includeBody)
    set rowObject to NSMutableDictionary's dictionary()
    tell application "Mail"
        rowObject's setObject:(id of messageObject as integer) forKey:"native_id"
        my putNullableText(rowObject, "rfc_message_id", message id of messageObject)
        my putNullableText(rowObject, "subject", subject of messageObject)
        my putNullableText(rowObject, "sender", sender of messageObject)
        my putNullableText(rowObject, "date_received", my isoDate(date received of messageObject))
        my putNullableText(rowObject, "date_sent", my isoDate(date sent of messageObject))
        rowObject's setObject:(read status of messageObject as boolean) forKey:"read_status"
        rowObject's setObject:(flagged status of messageObject as boolean) forKey:"flagged_status"
        rowObject's setObject:(message size of messageObject as integer) forKey:"message_size"
        rowObject's setObject:(count of mail attachments of messageObject) forKey:"attachment_count"
        rowObject's setObject:(my recipientAddresses(to recipients of messageObject)) forKey:"to"
        rowObject's setObject:(my recipientAddresses(cc recipients of messageObject)) forKey:"cc"
        rowObject's setObject:(my recipientAddresses(bcc recipients of messageObject)) forKey:"bcc"
        if includeBody then
            try
                rowObject's setObject:(content of messageObject as text) forKey:"body"
            on error
                rowObject's setObject:"" forKey:"body"
            end try
        end if
    end tell
    return rowObject
end messageRecord

on resolveMessage(accountID, pathArray, nativeID)
    set accountObject to my resolveAccount(accountID)
    set mailboxObject to my resolveMailbox(accountObject, pathArray)
    tell application "Mail"
        set matches to every message of mailboxObject whose id is nativeID
    end tell
    if (count of matches) is 0 then error "Message is unavailable" number 9202
    if (count of matches) is not 1 then error "Message identity is ambiguous" number 9203
    return item 1 of matches
end resolveMessage

on listMessagesAction(paramsObject)
    set accountObject to my resolveAccount(my textValue(paramsObject, "account_id", ""))
    set mailboxObject to my resolveMailbox(accountObject, my arrayValue(paramsObject, "mailbox_path"))
    set rowOffset to my integerValue(paramsObject, "offset", 0)
    set rowLimit to my integerValue(paramsObject, "limit", 25)
    set includeBody to my booleanValue(paramsObject, "include_body", false)
    if rowOffset < 0 or rowLimit < 1 or rowLimit > 100 then error "Invalid page bounds" number 9201
    tell application "Mail" to set totalCount to count of messages of mailboxObject
    set rows to NSMutableArray's array()
    set startIndex to rowOffset + 1
    set endIndex to rowOffset + rowLimit
    if endIndex > totalCount then set endIndex to totalCount
    if startIndex <= totalCount then
        tell application "Mail" to set selectedMessages to messages startIndex thru endIndex of mailboxObject
        repeat with messageObject in selectedMessages
            rows's addObject:(my messageRecord(messageObject, includeBody))
        end repeat
    end if
    set resultObject to NSMutableDictionary's dictionary()
    resultObject's setObject:rows forKey:"messages"
    resultObject's setObject:totalCount forKey:"total_count"
    if endIndex < totalCount then
        resultObject's setObject:endIndex forKey:"next_offset"
    else
        resultObject's setObject:(current application's NSNull's |null|()) forKey:"next_offset"
    end if
    return resultObject
end listMessagesAction

on getMessageAction(paramsObject)
    set messageObject to my resolveMessage(my textValue(paramsObject, "account_id", ""), my arrayValue(paramsObject, "mailbox_path"), my integerValue(paramsObject, "native_id", -1))
    set resultObject to NSMutableDictionary's dictionary()
    resultObject's setObject:(my messageRecord(messageObject, my booleanValue(paramsObject, "include_body", true))) forKey:"message"
    return resultObject
end getMessageAction

on findMessageAction(paramsObject)
    set accountObject to my resolveAccount(my textValue(paramsObject, "account_id", ""))
    set mailboxObject to my resolveMailbox(accountObject, my arrayValue(paramsObject, "mailbox_path"))
    set targetMessageID to my textValue(paramsObject, "rfc_message_id", "")
    if targetMessageID is "" then error "Message-ID is required" number 9201
    tell application "Mail"
        set matches to every message of mailboxObject whose message id is targetMessageID
    end tell
    if (count of matches) is 0 then error "Message is unavailable" number 9202
    if (count of matches) is not 1 then error "Message identity is ambiguous" number 9203
    set resultObject to NSMutableDictionary's dictionary()
    resultObject's setObject:(my messageRecord(item 1 of matches, false)) forKey:"message"
    return resultObject
end findMessageAction

on attachmentRecord(attachmentObject)
    set rowObject to NSMutableDictionary's dictionary()
    tell application "Mail"
        rowObject's setObject:(id of attachmentObject as text) forKey:"attachment_id"
        my putNullableText(rowObject, "name", name of attachmentObject)
        my putNullableText(rowObject, "mime_type", MIME type of attachmentObject)
        rowObject's setObject:(file size of attachmentObject as integer) forKey:"file_size"
        rowObject's setObject:(downloaded of attachmentObject as boolean) forKey:"downloaded"
    end tell
    return rowObject
end attachmentRecord

on resolveAttachment(messageObject, attachmentID)
    tell application "Mail" to set matches to every mail attachment of messageObject whose id is attachmentID
    if (count of matches) is 0 then error "Attachment is unavailable" number 9202
    if (count of matches) is not 1 then error "Attachment identity is ambiguous" number 9203
    return item 1 of matches
end resolveAttachment

on listAttachmentsAction(paramsObject)
    set messageObject to my resolveMessage(my textValue(paramsObject, "account_id", ""), my arrayValue(paramsObject, "mailbox_path"), my integerValue(paramsObject, "native_id", -1))
    set rows to NSMutableArray's array()
    tell application "Mail" to set attachmentObjects to every mail attachment of messageObject
    repeat with attachmentObject in attachmentObjects
        rows's addObject:(my attachmentRecord(attachmentObject))
    end repeat
    set resultObject to NSMutableDictionary's dictionary()
    resultObject's setObject:(my messageRecord(messageObject, false)) forKey:"message"
    resultObject's setObject:rows forKey:"attachments"
    return resultObject
end listAttachmentsAction

on fetchAttachmentAction(paramsObject)
    set messageObject to my resolveMessage(my textValue(paramsObject, "account_id", ""), my arrayValue(paramsObject, "mailbox_path"), my integerValue(paramsObject, "native_id", -1))
    set attachmentObject to my resolveAttachment(messageObject, my textValue(paramsObject, "attachment_id", ""))
    set outputPath to my textValue(paramsObject, "output_path", "")
    if outputPath is "" then error "Output path is invalid" number 9201
    tell application "Mail" to save attachmentObject in POSIX file outputPath
    set resultObject to NSMutableDictionary's dictionary()
    resultObject's setObject:(my messageRecord(messageObject, false)) forKey:"message"
    resultObject's setObject:(my attachmentRecord(attachmentObject)) forKey:"attachment"
    return resultObject
end fetchAttachmentAction

on addRecipients(draftObject, addressesObject, recipientKind)
    set addressCount to addressesObject's |count|()
    if addressCount is 0 then return
    tell application "Mail"
        repeat with addressIndex from 0 to (addressCount - 1)
            set addressText to (addressesObject's objectAtIndex:addressIndex) as text
            if recipientKind is "to" then
                tell draftObject to make new to recipient at end of to recipients with properties {address:addressText}
            else if recipientKind is "cc" then
                tell draftObject to make new cc recipient at end of cc recipients with properties {address:addressText}
            else
                tell draftObject to make new bcc recipient at end of bcc recipients with properties {address:addressText}
            end if
        end repeat
    end tell
end addRecipients

on addDraftAttachments(draftObject, attachmentPaths)
    set attachmentCount to attachmentPaths's |count|()
    if attachmentCount is 0 then return
    tell application "Mail"
        repeat with attachmentIndex from 0 to (attachmentCount - 1)
            set attachmentPath to (attachmentPaths's objectAtIndex:attachmentIndex) as text
            set attachmentFile to POSIX file attachmentPath as alias
            tell content of draftObject to make new attachment with properties {file name:attachmentFile} at after last paragraph
        end repeat
    end tell
end addDraftAttachments

on createDraftAction(paramsObject)
    set draftKind to my textValue(paramsObject, "draft_type", "new")
    set subjectText to my textValue(paramsObject, "subject", "")
    set bodyText to my textValue(paramsObject, "body", "")
    set accountObject to my resolveAccount(my textValue(paramsObject, "account_id", ""))
    tell application "Mail"
        if draftKind is "new" then
            set draftObject to make new outgoing message with properties {subject:subjectText, content:bodyText, visible:true}
        else
            set sourceMessage to my resolveMessage(my textValue(paramsObject, "account_id", ""), my arrayValue(paramsObject, "mailbox_path"), my integerValue(paramsObject, "native_id", -1))
            if draftKind is "reply" then
                set draftObject to reply sourceMessage opening window true reply to all false
            else if draftKind is "reply_all" then
                set draftObject to reply sourceMessage opening window true reply to all true
            else if draftKind is "forward" then
                set draftObject to forward sourceMessage opening window true
            else
                error "Draft type is invalid" number 9201
            end if
            if bodyText is not "" then set content of draftObject to bodyText & return & return & (content of draftObject as text)
            if subjectText is not "" then set subject of draftObject to subjectText
        end if
        try
            set accountAddresses to email addresses of accountObject
            if (count of accountAddresses) > 0 then set sender of draftObject to item 1 of accountAddresses
        end try
    end tell
    my addRecipients(draftObject, my arrayValue(paramsObject, "to"), "to")
    my addRecipients(draftObject, my arrayValue(paramsObject, "cc"), "cc")
    my addRecipients(draftObject, my arrayValue(paramsObject, "bcc"), "bcc")
    my addDraftAttachments(draftObject, my arrayValue(paramsObject, "attachment_paths"))
    tell application "Mail"
        save draftObject
        set visible of draftObject to true
        activate
        set resultObject to NSMutableDictionary's dictionary()
        resultObject's setObject:(id of draftObject as integer) forKey:"draft_id"
        my putNullableText(resultObject, "sender", sender of draftObject)
        my putNullableText(resultObject, "subject", subject of draftObject)
        resultObject's setObject:(my recipientAddresses(to recipients of draftObject)) forKey:"to"
        resultObject's setObject:(my recipientAddresses(cc recipients of draftObject)) forKey:"cc"
        resultObject's setObject:(my recipientAddresses(bcc recipients of draftObject)) forKey:"bcc"
        resultObject's setObject:true forKey:"visible"
        resultObject's setObject:false forKey:"sent"
        try
            set attachmentNames to NSMutableArray's array()
            set savedAttachments to every mail attachment of draftObject
            repeat with savedAttachment in savedAttachments
                try
                    attachmentNames's addObject:(name of savedAttachment as text)
                end try
            end repeat
            resultObject's setObject:(count of savedAttachments) forKey:"attachment_count"
            resultObject's setObject:attachmentNames forKey:"attachment_names"
            resultObject's setObject:true forKey:"attachment_readback_supported"
        on error
            resultObject's setObject:-1 forKey:"attachment_count"
            resultObject's setObject:(NSMutableArray's array()) forKey:"attachment_names"
            resultObject's setObject:false forKey:"attachment_readback_supported"
        end try
    end tell
    return resultObject
end createDraftAction

on mutateMessageAction(paramsObject)
    set messageObject to my resolveMessage(my textValue(paramsObject, "account_id", ""), my arrayValue(paramsObject, "mailbox_path"), my integerValue(paramsObject, "native_id", -1))
    set actionName to my textValue(paramsObject, "mutation", "")
    tell application "Mail"
        if actionName is "mark_read" then
            set read status of messageObject to true
        else if actionName is "mark_unread" then
            set read status of messageObject to false
        else if actionName is "flag" then
            set flagged status of messageObject to true
        else if actionName is "unflag" then
            set flagged status of messageObject to false
        else if actionName is "move" or actionName is "trash" then
            set accountObject to my resolveAccount(my textValue(paramsObject, "account_id", ""))
            set destinationMailbox to my resolveMailbox(accountObject, my arrayValue(paramsObject, "destination_path"))
            move messageObject to destinationMailbox
        else
            error "Mutation is invalid" number 9201
        end if
    end tell
    set resultObject to NSMutableDictionary's dictionary()
    resultObject's setObject:(my messageRecord(messageObject, false)) forKey:"message"
    return resultObject
end mutateMessageAction
