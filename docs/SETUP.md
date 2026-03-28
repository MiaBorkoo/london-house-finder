# Setup Guide

## Prerequisites

- GitHub account
- Smartphone with ntfy app ([iOS](https://apps.apple.com/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy))
- (Optional) Anthropic API key for floor plan analysis

## Step 1: Fork the Repository

1. Click "Fork" on GitHub
2. Name it `london-house-finder`

## Step 2: Set Up ntfy

1. Install the ntfy app on your phone
2. Choose a unique topic name (e.g. `london-flat-lu-2026`)
3. Subscribe to this topic in the app

## Step 3: Create Google Sheet (Optional)

This lets you edit search criteria from your phone.

1. Go to [Google Sheets](https://sheets.google.com) and create a new spreadsheet
2. Name it "London House Finder Config"
3. Create tab **Settings** with columns: `Key`, `Value`
4. Create tab **Areas** with columns: `Area Name`, `Postcode`, `Rightmove ID`, `Zoopla Query`, `OnTheMarket Outcode`, `Enabled`
5. Create tab **Target Stations** with columns: `Station Name`, `Latitude`, `Longitude`, `Max Walk Minutes`
6. Fill in your criteria (see README for example data)
7. Click **Share** > **Anyone with the link** > **Viewer**
8. Copy the Sheet ID from the URL: `https://docs.google.com/spreadsheets/d/THIS_IS_THE_ID/edit`

## Step 4: Add GitHub Secrets

1. Go to your repo > **Settings** > **Secrets and variables** > **Actions**
2. Add these secrets:
   - `NTFY_TOPIC`: your topic name from Step 2
   - `CONFIG_SHEET_ID`: the sheet ID from Step 3 (skip if not using Sheets)
   - `ANTHROPIC_API_KEY`: your Anthropic key (optional, for floor plan analysis)

## Step 5: Enable GitHub Actions

1. Go to the **Actions** tab
2. Click "I understand my workflows, go ahead and enable them"
3. Click "London House Finder" workflow
4. Click **Run workflow** to test

## Step 6: Verify

1. Wait for the workflow to complete
2. Check your phone for a notification
3. Check Actions logs for any errors

## Editing Config from Phone

1. Open Google Sheets app
2. Change any value (e.g. max price)
3. Changes take effect on the next scheduled run (max 30 minutes)

## Finding Rightmove Location IDs

1. Go to rightmove.co.uk
2. Search for your area
3. Look at the URL: `locationIdentifier=REGION%5EXXXXX`
4. The `REGION^XXXXX` is your Rightmove ID (URL-decode `%5E` to `^`)

## Troubleshooting

- **No notifications?** Check ntfy topic matches in both the app and GitHub secrets
- **Scraper blocked?** The workflow uses browser impersonation, but sites may still block. Check Actions logs
- **No sqm data?** Set `ANTHROPIC_API_KEY` secret, or check if floor plans are available on the listings
- **Wrong area results?** Verify Rightmove IDs by searching manually on rightmove.co.uk
