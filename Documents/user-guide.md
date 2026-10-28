# User Guide

Document Intelligence reads invoices (and receipts and ID documents) and gives you the fields you choose, each
with a confidence score, so you can check them, correct them and export them.

- [Signing in and roles](#signing-in-and-roles)
- [Extract: choose fields, upload, review](#extract-choose-fields-upload-review)
- [Include images: typed text only, or pictures too](#include-images-typed-text-only-or-pictures-too)
- [Many documents at once: one Excel file](#many-documents-at-once-one-excel-file)
- [What confidence means](#what-confidence-means)
- [Correcting values](#correcting-values)
- [Exports](#exports)
- [History](#history)
- [Settings (Admins)](#settings-admins)
- [Privacy and retention](#privacy-and-retention)
- [A 10-minute demo](#a-10-minute-demo)
- [FAQ](#faq)
- [Troubleshooting](#troubleshooting)

## Signing in and roles

Enter the shared password and choose a role:

| Role | Can |
|---|---|
| **User** | Extract, review, correct, export, see History, delete documents uploaded in their own session |
| **Admin** | Everything a User can, plus manage presets and settings, and delete any document |

Five wrong passwords from the same address pause sign-in for 15 minutes. A shared password with a role choice is
meant for demos; sign-in with your organisation account (Microsoft Entra ID) is planned.

## Extract: choose fields, upload, review

The Extract page has three steps.

**1. Choose model and fields.** Pick the model that matches the document: **Invoice** (default), **Receipt** or
**ID document**. (*Business card* is shown but unavailable: Microsoft retired that model in the API version this app
uses.) Pick a **preset** to tick a ready-made set of fields, then add or remove ticks. Use the search box to find a
field, **All** on a group, or **Select all** and **Clear**. The counter shows how many fields are selected.
**Remember my selection** keeps your ticks in this browser; it then appears as *My saved selection*.

Invoice presets:

| Preset | Fields |
|---|---|
| Accounts payable basics | vendor, invoice number, invoice and due date, currency, subtotal, tax, total, amount due |
| Header with addresses | vendor and customer with addresses and tax IDs, billing and shipping addresses, invoice number, dates, purchase order, payment terms |
| Full invoice with line items | the header, amounts, tax details and every line item |
| Tax review | tax IDs, subtotal, tax, tax details, total |

Under the fields, the **Include images** switch decides whether text inside pictures is read and whether pictures
are extracted (see [Include images](#include-images-typed-text-only-or-pictures-too)). It is off by default.

**2. Upload.** Drop one or more files on the upload area, or click it (or press Enter on it) to browse. PDF, JPEG
and PNG are accepted, up to 10 MB and 10 pages per file and up to 100 files at once. Files that do not qualify are
refused at once with the reason. No document at hand? Pick a sample under **Try a sample** and press the button;
the model switches to the sample's model if needed. Each file shows its status: *Queued*, *Processing*, *Done* or
*Failed*. For several files, see [Many documents at once](#many-documents-at-once-one-excel-file).

**3. Review.** The first document opens automatically; open others with **Review**. The top strip shows the file,
model, API version, pages, time taken and how many fields need review. On the left is the document; boxes mark
where each value was found (amber boxes need review). On the right is the field table:

- Point at a row (or move to it with the keyboard) and its box lights up; the page turns if needed.
- Click a box and its row is selected.
- **Not found** means the model did not find that field on this document.
- **Review** means the confidence is below the review threshold (80% unless an Admin changed it).
- *Printed:* shows the text exactly as printed when it differs from the normalised value (dates become
  `YYYY-MM-DD`, amounts become a number and a currency code, addresses one line).
- Line items appear as a table under the fields. Point at a cell to see its confidence.

Use **Change fields** to show other fields of the same document. The document is not analysed again, and nothing
is charged again.

## Include images: typed text only, or pictures too

Document Intelligence reads every piece of text it can see, including text inside pictures. On an invoice that can
mean the company name is taken from the **logo** (a brand name such as "NOVAPRINT") instead of the **typed legal
name** ("Shreeji Novaprint Solutions Pvt. Ltd.").

| Include images | What happens |
|---|---|
| **Off** (default) | Only typed text is read. For PDFs with a text layer, the app leaves embedded pictures (logos, stamps, photos) out of the file before it is analysed, so values come from the typed text. No pictures are extracted. |
| **On** | The file is analysed as it is, so text inside pictures is read too. In addition, the pictures themselves are extracted (for example the photo of the person on an ID card) and shown under **Pictures** in the review, where you can point at them to see where they are, download them one by one or all together. This needs a second analysis (by Microsoft's Layout model), so **pages count twice** against the daily page limit. |

Photos and scans (JPEG and PNG files, and PDF pages without typed text) are one big picture: there is no typed text
to keep apart from the logo. With the switch off they are still read as they are, and the review says so.
The review always states which way a document was read, for example "Typed text only: 1 image was left out of the
analysis".

## Many documents at once: one Excel file

1. Choose the model, fields and the **Include images** setting; they apply to every file in the upload.
2. Drop all the files at once (up to 100). They are sent one after another into one *batch*; the progress shows
   which file is being sent.
3. The panel **This upload** shows how many documents have finished, and every document's status. You can open any
   finished document with **Review** while the rest are still running.
4. **Download Excel** stays locked ("Waiting…") until **every** document of the batch has finished. Then the panel
   turns green and offers one Excel file for all documents (plus CSV, JSON and, if pictures were extracted, a ZIP
   of the pictures). With **Download the Excel file automatically when every document has finished** ticked (the
   default), the file downloads by itself at that moment.

The Excel file has one row per document in the sheet *Documents*, with a *Status* column; documents that failed are
listed too, with the reason in *Problem*, so the file accounts for every document you uploaded. Line items of all
documents are in *Line items*, every value with its confidence is in *Details*, and extracted pictures are listed in
*Pictures* (the files themselves are in the pictures ZIP). If a document failed, you can **Retry** it and download
the Excel file again afterwards.

## What confidence means

Confidence (0 to 100%) is the model's own estimate of how likely the value is right. It is not a guarantee: a 95%
field can still be wrong, and a 70% field is often right. Fields below the threshold are flagged so you look at
them first. Typical reasons for low confidence: a poor scan, handwriting, an unusual layout, a stamp or fold over
the text, or two similar values (for example two dates).

What to do with a **Review** field: compare it with the highlighted spot on the document. If it is right, press
the check mark (**Mark reviewed**). If it is wrong, correct it. **Mark all reviewed** accepts every field.

## Correcting values

Press the pencil on a field (or double-click a line-item cell, or press Enter on it) to correct it. The dialog
shows the model value, the printed text and the confidence. Saving keeps the model value alongside your correction,
marks the field reviewed and shows an **Edited** chip. **Use model value** undoes a correction. Exports use the
corrected value and say which fields were edited.

## Exports

From the review: **Export → Copy JSON, Download JSON, CSV or XLSX**. From an upload of several files: **Export
all**. From History: tick documents and choose a format.

| Format | What you get |
|---|---|
| CSV | One row per document: status, the selected fields and a confidence column for each |
| XLSX | Sheet *Documents* (one row per document, with status and any problem), *Line items* (one row per line, with the document name), *Details* (every value with raw text, confidence, review flag, edited flag, model value), *Pictures* (when pictures were extracted) |
| JSON | Everything: the selected fields with confidence and boxes, your corrections, and the full result |

Only the selected fields are exported. Fields the model did not find say "Not found".

## History

History lists every analysed document with model, status, pages, the number of fields to review and the upload
time. Search by file name, filter by model and status, show only documents that need review or those uploaded in
your session, and sort. **Open** shows the review. The bin icon deletes a document and its file now, after you
confirm.

## Settings (Admins)

- **Review threshold**: the confidence below which a field is flagged (default 0.80).
- **Daily page limit**: pages all users together may analyse per day (default 200). New uploads are refused once it
  is reached.
- **Maximum pages per file** (default 10).
- **Presets**: create, edit (including built-in ones) and delete presets for each model. Changes apply at once.

Retention and the maximum file size are set by the deployment and shown for information.

## Privacy and retention

Invoices contain personal and financial data. Uploaded files and results are deleted automatically after the
retention period (7 days in the demo), and you can delete a document and its file at any time from History or from
the review. The app never writes field values to its logs. Do not upload documents you are not allowed to process.

## A 10-minute demo

1. **Sign in** as Admin (1 min). Point out the two roles.
2. **Choose fields** (1 min): Invoice, preset *Accounts payable basics*, then switch to *Full invoice with line
   items*. Search for "tax".
3. **Try a sample** (2 min): *Software services, Indian GST*. Show the summary strip, the boxes, hovering rows, the
   *derived* currency, line items and the *Review* chip on the purchase order.
4. **Correct a value** (1 min): fix the purchase order, show the *Edited* chip and the model value.
5. **Not found** (1 min): *Change fields*, tick *Shipping address*: it is not on this invoice, so it shows *Not
   found*, with no new analysis.
6. **Batch** (2 min): drop three sample files from `Data/sample_invoices` (for example the UK, EU and scanned
   ones), watch the statuses, open the scanned PNG (lower confidence, rotated page, boxes still on the text), then
   **Export all → XLSX** and open the three sheets.
7. **History and Settings** (2 min): filter *Needs review*, delete a document, change the review threshold, create
   a preset and pick it on Extract.

## FAQ

**Which languages work?** The UI is in English. The invoice model reads invoices in the languages Microsoft
supports for it (for example English, including India, plus several European languages); results for other
languages and scripts depend on the model.

**Can I add my own fields?** Not in this version: only the fields the pre-built models return. Custom models for
company-specific documents are planned.

**Why is a field "Not found" when I can see it?** The pre-built model did not recognise it as that field, for
example a label it does not expect. Correct it by hand, or report the example.

**Why did it take the company name from the logo?** The service reads text inside pictures too. Leave **Include
images** off (the default) so only typed text is read; for photos and scans this cannot be separated.

**How do I get the photo from an ID card?** Turn **Include images** on before uploading. The photo appears under
**Pictures** in the review and can be downloaded.

**Does changing the selected fields cost anything?** No. The document is analysed once and every field the model
found is kept.

**How many pages are counted?** Every page of each file, when the file is accepted (twice with **Include images**
on), and again if a failed file is retried.

**Why are my sample results the same every time?** On a machine in local mode the results are a mock. In Azure they
come from Document Intelligence.

## Troubleshooting

| Message | What to do |
|---|---|
| Only PDF, JPEG and PNG files are accepted | Convert the file (for example print to PDF). |
| The content does not match the file type | The file was renamed (for example a PNG called `.pdf`). Use its real extension. |
| The PDF is password-protected | Remove the password and upload again. |
| The PDF has N pages; the limit is 10 | Split the PDF, or ask an Admin to raise the limit. |
| The daily page limit is reached | Try again tomorrow, or ask an Admin to raise it. |
| Document Intelligence is busy (HTTP 429) | Wait a minute and press **Retry**. |
| The quota is used up | The free tier's monthly pages are used; ask the administrator. |
| Could not read this file | The file may be damaged, blank, too small or a format the model cannot read. |
| Sign-in is not configured | The administrator has not set the password yet. |
| Too many wrong passwords | Wait 15 minutes. |
| The preview could not be loaded | The fields are still correct; reload the page. |
