import imaplib
import email
from email.header import decode_header
import openai
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from textblob import TextBlob
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime, timedelta
import shutil
import json

EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("EMAIL_PASSWORD")
IMAP_SERVER = "imap.gmail.com"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
openai.api_key = os.getenv("OPENAI_API_KEY")

logging.basicConfig(filename='email_ai.log', level=logging.INFO)

scheduler = BlockingScheduler()

attachment_directory = "attachments"

def fetch_emails(n=5):
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")

        _, messages = mail.search(None, "UNSEEN")
        if not messages[0]:
            print("No unread emails.")
            return []

        message_ids = messages[0].split()[-n:]
        emails = []

        for num in message_ids:
            _, data = mail.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(data[0][1])
            subject, _ = decode_header(msg["Subject"])[0]
            subject = subject.decode() if isinstance(subject, bytes) else subject
            from_ = msg.get("From")

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                        body = part.get_payload(decode=True).decode(errors="ignore")
                        break
            else:
                body = msg.get_payload(decode=True).decode(errors="ignore")

            attachments = []
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    disposition = str(part.get("Content-Disposition"))
                    if "attachment" in disposition:
                        filename = part.get_filename()
                        if filename:
                            attachments.append(filename)

            emails.append({"from": from_, "subject": subject, "body": body, "attachments": attachments})
        return emails

    except Exception as e:
        logging.error(f"Error fetching emails: {e}")
        return []

def summarize_email(email_text):
    try:
        prompt = f"Summarize this email and suggest a 1-liner reply:\n\n{email_text}"
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant for email management."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4
        )
        return response.choices[0].message["content"]
    except Exception as e:
        logging.error(f"Error summarizing email: {e}")
        return "Error generating summary"

def analyze_sentiment(email_text):
    blob = TextBlob(email_text)
    sentiment = blob.sentiment.polarity
    if sentiment > 0.1:
        return "positive"
    elif sentiment < -0.1:
        return "negative"
    else:
        return "neutral"

def categorize_email(email_text):
    categories = ["work", "personal", "spam"]
    if "invoice" in email_text or "project" in email_text:
        return "work"
    elif "party" in email_text or "friend" in email_text:
        return "personal"
    else:
        return "spam"

def download_attachments(mail):
    if not os.path.exists(attachment_directory):
        os.makedirs(attachment_directory)

    for attachment in mail["attachments"]:
        print(f"Downloading attachment: {attachment}")
        attachment_path = os.path.join(attachment_directory, attachment)
        with open(attachment_path, "wb") as f:
            f.write(attachment)

def forward_email(to, subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL
        msg['To'] = to
        msg['Subject'] = f"Fwd: {subject}"

        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL, PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL, to, text)
        server.quit()

        logging.info(f"Forwarded email to {to} with subject {subject}")
        print(f"Forwarded email to {to} with subject {subject}")
    except Exception as e:
        logging.error(f"Error forwarding email: {e}")
        print(f"Error forwarding email: {e}")

def scheduled_email_check():
    emails = fetch_emails()
    if emails:
        for i, mail in enumerate(emails, 1):
            print(f"\n--- Email #{i} ---")
            print(f"From: {mail['from']}")
            print(f"Subject: {mail['subject']}")

            sentiment = analyze_sentiment(mail["body"])
            print(f"Sentiment: {sentiment}")

            summary = summarize_email(mail["body"])
            print(f"AI Summary + Reply Suggestion:\n{summary}")

            category = categorize_email(mail["body"])
            print(f"Category: {category}")

            if mail["attachments"]:
                download_attachments(mail)

            if sentiment == "positive" or "urgent" in mail["subject"].lower():
                send_reply(mail["from"], mail["subject"], f"Thank you for your email! Here's a quick response: {summary}")
            else:
                print("No reply sent due to negative sentiment or low priority.")

            if category == "spam":
                forward_email("spam@yourdomain.com", mail["subject"], mail["body"])

    else:
        print("No new emails to process.")

scheduler.add_job(scheduled_email_check, 'interval', minutes=30)

if __name__ == "__main__":
    print("Starting email assistant...")
    scheduler.start()
