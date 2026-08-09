from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_file
from flask_cors import CORS
from functools import wraps
import os
import uuid
import requests
from datetime import datetime, timedelta
import io
import csv
import json
import urllib.parse

app = Flask(__name__)
app.secret_key = 'handshake-secret-key-2026'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
CORS(app)

# ============================================================
# SUPABASE CONFIG
# ============================================================
SUPABASE_URL = 'https://ocikxcyckwigrvtwxsap.supabase.co'
SUPABASE_KEY = 'sb_publishable_f3zLVxnd9ZlV4JiwxFBVPg_UkDDNKVm'

# ============================================================
# TEMPLATE CONTEXT PROCESSOR - WhatsApp Helpers
# ============================================================

@app.context_processor
def utility_processor():
    def generate_whatsapp_link(phone_number, message):
        """Generate WhatsApp click-to-chat link"""
        if not phone_number:
            return '#'
        # Clean phone number (remove + and spaces)
        phone_number = ''.join(filter(str.isdigit, str(phone_number)))
        # Remove leading 0 if present
        if phone_number.startswith('0'):
            phone_number = phone_number[1:]
        encoded_message = urllib.parse.quote(message)
        return f"https://wa.me/{phone_number}?text={encoded_message}"
    
    def generate_whatsapp_login_link(worker):
        """Generate WhatsApp link with login credentials pre-filled"""
        name = worker.get('name', 'Worker')
        email = worker.get('email', '')
        password = worker.get('password', 'temp123')
        whatsapp = worker.get('whatsapp', '')
        
        if not whatsapp:
            return '#'
        
        message = f"""🔐 Handshake Manager - Login Credentials

Hello {name}! 👋

Your account has been created. Here are your login details:

Email: {email}
Password: {password}

Login URL: https://handshake-manager.vercel.app/login

Please change your password after first login."""
        
        return generate_whatsapp_link(whatsapp, message)
    
    def generate_whatsapp_account_link(worker, account):
        """Generate WhatsApp link with account assignment pre-filled"""
        name = worker.get('name', 'Worker')
        account_name = account.get('name', 'Unknown Account')
        platform = account.get('platform', 'Unknown Platform')
        whatsapp = worker.get('whatsapp', '')
        
        if not whatsapp:
            return '#'
        
        message = f"""📋 Account Assignment

Hello {name}! 👋

You have been assigned to a new account:

Account: {account_name}
Platform: {platform}
Location: {account.get('location', 'N/A')}

Please check your dashboard for more details."""
        
        return generate_whatsapp_link(whatsapp, message)
    
    return {
        'generate_whatsapp_link': generate_whatsapp_link,
        'generate_whatsapp_login_link': generate_whatsapp_login_link,
        'generate_whatsapp_account_link': generate_whatsapp_account_link
    }

# ============================================================
# SUPABASE FUNCTIONS
# ============================================================

def supabase_request(method, table, data=None, filters=None):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }
    
    if filters:
        params = '&'.join([f"{k}=eq.{v}" for k, v in filters.items()])
        url = f"{url}?{params}"
    
    try:
        if method == 'GET':
            response = requests.get(url, headers=headers, timeout=10)
        elif method == 'POST':
            response = requests.post(url, headers=headers, json=data, timeout=10)
        elif method == 'PATCH':
            response = requests.patch(url, headers=headers, json=data, timeout=10)
        elif method == 'DELETE':
            response = requests.delete(url, headers=headers, timeout=10)
        
        if response.status_code in [200, 201, 204]:
            return {'data': response.json() if response.text else []}
        else:
            raise Exception(f"Error: {response.status_code} - {response.text}")
    except requests.exceptions.Timeout:
        raise Exception("Request timed out. Please try again.")
    except requests.exceptions.ConnectionError:
        raise Exception("Connection error. Please check your internet.")

# ============================================================
# SAFE NUMBER HELPER
# ============================================================

def safe_float(value, default=0.0):
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def safe_str(value, default=''):
    if value is None:
        return default
    return str(value)

def safe_int(value, default=0):
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def build_lookups():
    accounts_data = supabase_request('GET', 'hs_accounts')
    workers_data = supabase_request('GET', 'hs_users', filters={'role': 'worker'})
    proxies_data = supabase_request('GET', 'hs_proxies')
    managers_data = supabase_request('GET', 'hs_users', filters={'role': 'manager'})
    
    account_dict = {}
    if accounts_data['data']:
        for acc in accounts_data['data']:
            account_dict[acc['id']] = acc
    
    worker_dict = {}
    if workers_data['data']:
        for w in workers_data['data']:
            worker_dict[w['id']] = w
    
    proxy_dict = {}
    if proxies_data['data']:
        for p in proxies_data['data']:
            proxy_dict[p['id']] = p
    
    manager_dict = {}
    if managers_data['data']:
        for m in managers_data['data']:
            manager_dict[m['id']] = m
    
    return account_dict, worker_dict, proxy_dict, manager_dict

def get_handshake_stats():
    try:
        accounts = supabase_request('GET', 'hs_accounts')
        workers = supabase_request('GET', 'hs_users', filters={'role': 'worker'})
        submissions = supabase_request('GET', 'hs_submissions')
        assignments = supabase_request('GET', 'hs_worker_assignments')
        managers = supabase_request('GET', 'hs_users', filters={'role': 'manager'})
        
        # Get unread announcements count
        unread_count = 0
        try:
            announcements = supabase_request('GET', 'hs_announcements')
            user_id = session.get('user_id')
            if announcements['data'] and user_id:
                for a in announcements['data']:
                    read_by = json.loads(a.get('read_by', '[]'))
                    if user_id not in read_by:
                        unread_count += 1
        except:
            pass
        
        pending = len([s for s in submissions['data'] if s.get('status') == 'pending']) if submissions['data'] else 0
        payment_proofs = len([s for s in submissions['data'] if s.get('submission_type') == 'payment_proof' and s.get('status') != 'paid']) if submissions['data'] else 0
        approved = len([s for s in submissions['data'] if s.get('status') == 'approved']) if submissions['data'] else 0
        rejected = len([s for s in submissions['data'] if s.get('status') == 'rejected']) if submissions['data'] else 0
        paid = len([s for s in submissions['data'] if s.get('status') == 'paid']) if submissions['data'] else 0
        
        total_hours = sum(safe_float(s.get('hours')) for s in submissions['data']) if submissions['data'] else 0
        total_earnings = sum(safe_float(s.get('total_earnings_usd')) for s in submissions['data']) if submissions['data'] else 0
        total_payout = sum(safe_float(s.get('worker_payout_usd')) for s in submissions['data']) if submissions['data'] else 0
        
        return {
            'total_accounts': len(accounts['data']) if accounts['data'] else 0,
            'total_workers': len(workers['data']) if workers['data'] else 0,
            'total_managers': len(managers['data']) if managers['data'] else 0,
            'pending': pending,
            'approved': approved,
            'rejected': rejected,
            'paid': paid,
            'total_assignments': len(assignments['data']) if assignments['data'] else 0,
            'payment_proofs': payment_proofs,
            'total_hours': total_hours,
            'total_earnings': total_earnings,
            'total_payout': total_payout,
            'unread_announcements': unread_count
        }
    except Exception as e:
        print(f"Error in get_handshake_stats: {e}")
        return {
            'total_accounts': 0,
            'total_workers': 0,
            'total_managers': 0,
            'pending': 0,
            'approved': 0,
            'rejected': 0,
            'paid': 0,
            'total_assignments': 0,
            'payment_proofs': 0,
            'total_hours': 0,
            'total_earnings': 0,
            'total_payout': 0,
            'unread_announcements': 0
        }

def get_settings():
    try:
        result = supabase_request('GET', 'hs_settings')
        if result['data'] and len(result['data']) > 0:
            settings = result['data'][0]
            return {
                'exchange_rate': safe_float(settings.get('exchange_rate'), 150),
                'default_worker_percentage': safe_float(settings.get('default_worker_percentage'), 10),
                'default_hourly_rate': safe_float(settings.get('default_hourly_rate'), 10),
                'default_client_rate': safe_float(settings.get('default_client_rate'), 15),
                'commission_percent': safe_float(settings.get('commission_percent'), 0),
                'updated_at': safe_str(settings.get('updated_at'), datetime.utcnow().isoformat())
            }
        return {
            'exchange_rate': 150,
            'default_worker_percentage': 10,
            'default_hourly_rate': 10,
            'default_client_rate': 15,
            'commission_percent': 0,
            'updated_at': datetime.utcnow().isoformat()
        }
    except Exception as e:
        print(f"Error getting settings: {e}")
        return {
            'exchange_rate': 150,
            'default_worker_percentage': 10,
            'default_hourly_rate': 10,
            'default_client_rate': 15,
            'commission_percent': 0,
            'updated_at': datetime.utcnow().isoformat()
        }

# ============================================================
# DECORATORS
# ============================================================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Not logged in'}), 401
            flash('Please login first', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_role' not in session or session['user_role'] != 'admin':
            flash('Admin access required', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_role' not in session or session['user_role'] not in ['admin', 'manager']:
            flash('Manager access required', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

# ============================================================
# AUTHENTICATION
# ============================================================

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            result = supabase_request('GET', 'hs_users', filters={'email': email})
            if result['data']:
                user = result['data'][0]
                if user.get('password') == password:
                    session['user_id'] = user['id']
                    session['user_name'] = user.get('name', 'User')
                    session['user_email'] = user.get('email', '')
                    session['user_role'] = user.get('role', 'worker')
                    flash('Login successful!', 'success')
                    
                    # ✅ CORRECT REDIRECT BASED ON ROLE
                    role = user.get('role', 'worker')
                    if role == 'admin':
                        return redirect(url_for('admin_dashboard'))
                    elif role == 'manager':
                        return redirect(url_for('manager_dashboard'))
                    else:
                        return redirect(url_for('worker_dashboard'))
                else:
                    flash('Invalid password', 'danger')
            else:
                flash('User not found', 'danger')
        except Exception as e:
            flash(f'Login error: {str(e)}', 'danger')
    
    return render_template('login.html', 
        prefilled_email='admin@handshake.com',
        prefilled_password='admin123'
    )

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out', 'success')
    return redirect(url_for('login'))

# ============================================================
# DASHBOARDS
# ============================================================

@app.route('/dashboard')
@login_required
def dashboard():
    role = session.get('user_role', 'worker')
    if role == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif role == 'manager':
        return redirect(url_for('manager_dashboard'))
    else:
        return redirect(url_for('worker_dashboard'))

@app.route('/admin-dashboard')
@login_required
@admin_required
def admin_dashboard():
    try:
        account_dict, worker_dict, proxy_dict, manager_dict = build_lookups()
        submissions_data = supabase_request('GET', 'hs_submissions')
        assignments_data = supabase_request('GET', 'hs_worker_assignments')
        settings = get_settings()
        
        total_accounts = len(account_dict)
        total_workers = len(worker_dict)
        total_managers = len(manager_dict)
        total_submissions = len(submissions_data['data']) if submissions_data['data'] else 0
        total_assignments = len(assignments_data['data']) if assignments_data['data'] else 0
        
        pending = 0
        approved = 0
        rejected = 0
        paid = 0
        total_hours = 0
        total_worker_payout = 0
        total_client_paid = 0
        total_your_revenue = 0
        total_worker_payout_all = 0
        pending_payment_proofs = 0
        total_payment_proofs = 0
        payment_proofs_pending_amount = 0
        
        pending_submissions = []
        recent_activity = []
        
        if submissions_data['data']:
            for s in submissions_data['data']:
                status = s.get('status')
                submission_type = s.get('submission_type', 'hours')
                
                hours = safe_float(s.get('hours'))
                total_earnings = safe_float(s.get('total_earnings_usd'))
                worker_payout = safe_float(s.get('worker_payout_usd'))
                commission = safe_float(s.get('commission_usd'))
                
                worker = worker_dict.get(s.get('worker_id'))
                s['worker_name'] = safe_str(worker.get('name', 'Unknown') if worker else 'Unknown')
                
                account = account_dict.get(s.get('account_id'))
                s['account_name'] = safe_str(account.get('name', 'Unknown') if account else 'Unknown')
                
                s['hours'] = hours
                s['total_earnings_usd'] = total_earnings
                s['worker_payout_usd'] = worker_payout
                s['commission_usd'] = commission
                s['your_revenue'] = total_earnings - worker_payout
                
                if submission_type == 'payment_proof':
                    total_payment_proofs += 1
                    if status == 'pending':
                        pending_payment_proofs += 1
                        payment_proofs_pending_amount += total_earnings
                    
                    if status == 'paid' or status == 'approved':
                        total_client_paid += total_earnings
                        total_worker_payout_all += worker_payout
                        total_your_revenue += commission if commission > 0 else (total_earnings - worker_payout)
                
                if status == 'pending':
                    pending += 1
                    pending_submissions.append(s)
                elif status == 'approved':
                    approved += 1
                    if submission_type == 'hours':
                        total_hours += hours
                        total_worker_payout += worker_payout
                        total_client_paid += total_earnings
                        total_worker_payout_all += worker_payout
                        total_your_revenue += commission if commission > 0 else (total_earnings - worker_payout)
                elif status == 'paid':
                    paid += 1
                    if submission_type == 'hours':
                        total_client_paid += total_earnings
                        total_worker_payout_all += worker_payout
                        total_your_revenue += commission if commission > 0 else (total_earnings - worker_payout)
                elif status == 'rejected':
                    rejected += 1
        
        recent = pending_submissions[:5]
        
        if submissions_data['data']:
            sorted_subs = sorted(submissions_data['data'], key=lambda x: x.get('created_at', ''), reverse=True)
            recent_activity = sorted_subs[:10]
            for act in recent_activity:
                worker = worker_dict.get(act.get('worker_id'))
                act['worker_name'] = safe_str(worker.get('name', 'Unknown') if worker else 'Unknown')
                account = account_dict.get(act.get('account_id'))
                act['account_name'] = safe_str(account.get('name', 'Unknown') if account else 'Unknown')
        
        avg_worker_percentage = 10
        if worker_dict:
            total_percentage = sum(safe_float(w.get('worker_percentage'), 10) for w in worker_dict.values())
            avg_worker_percentage = total_percentage / len(worker_dict) if worker_dict else 10
        
        worker_performance = []
        for wid, w in worker_dict.items():
            worker_subs = [s for s in submissions_data['data'] if s.get('worker_id') == wid] if submissions_data['data'] else []
            total_worker_hours = sum(safe_float(s.get('hours')) for s in worker_subs)
            total_worker_earnings = sum(safe_float(s.get('worker_payout_usd')) for s in worker_subs)
            total_worker_subs = len(worker_subs)
            
            worker_performance.append({
                'name': w.get('name', 'Unknown'),
                'hours': total_worker_hours,
                'earnings': total_worker_earnings,
                'submissions': total_worker_subs
            })
        
        worker_performance = sorted(worker_performance, key=lambda x: x['hours'], reverse=True)[:10]
        
        stats = {
            'total_accounts': total_accounts,
            'total_workers': total_workers,
            'total_managers': total_managers,
            'total_submissions': total_submissions,
            'total_assignments': total_assignments,
            'pending': pending,
            'approved': approved,
            'paid': paid,
            'rejected': rejected,
            'total_hours': total_hours,
            'total_worker_payout': total_worker_payout,
            'total_client_paid': total_client_paid,
            'your_revenue': total_your_revenue,
            'total_worker_payout_all': total_worker_payout_all,
            'exchange_rate': settings.get('exchange_rate', 150),
            'recent': recent,
            'recent_activity': recent_activity,
            'pending_payment_proofs': pending_payment_proofs,
            'total_payment_proofs': total_payment_proofs,
            'payment_proofs_pending_amount': payment_proofs_pending_amount,
            'avg_worker_percentage': round(avg_worker_percentage, 1),
            'worker_performance': worker_performance
        }
        
        # Add unread announcements count
        stats['unread_announcements'] = get_handshake_stats()['unread_announcements']
        
        return render_template('admin_dashboard.html', 
            stats=stats, 
            user_name=session.get('user_name'),
            now=datetime.now()
        )
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Error loading dashboard: {str(e)}', 'danger')
        return render_template('admin_dashboard.html', stats={
            'total_accounts': 0,
            'total_workers': 0,
            'total_managers': 0,
            'total_submissions': 0,
            'total_assignments': 0,
            'pending': 0,
            'approved': 0,
            'paid': 0,
            'rejected': 0,
            'total_hours': 0,
            'total_worker_payout': 0,
            'total_client_paid': 0,
            'your_revenue': 0,
            'total_worker_payout_all': 0,
            'exchange_rate': 150,
            'recent': [],
            'recent_activity': [],
            'pending_payment_proofs': 0,
            'total_payment_proofs': 0,
            'payment_proofs_pending_amount': 0,
            'avg_worker_percentage': 10,
            'worker_performance': [],
            'unread_announcements': 0
        }, user_name=session.get('user_name'), now=datetime.now())

@app.route('/manager-dashboard')
@login_required
@manager_required
def manager_dashboard():
    user_id = session['user_id']
    
    try:
        assignments = supabase_request('GET', 'hs_manager_assignments', filters={'manager_id': user_id})
        account_ids = [a['account_id'] for a in assignments['data']] if assignments['data'] else []
        
        accounts = []
        submissions = []
        if account_ids:
            for acc_id in account_ids:
                acc = supabase_request('GET', 'hs_accounts', filters={'id': acc_id})
                if acc['data']:
                    accounts.append(acc['data'][0])
                acc_submissions = supabase_request('GET', 'hs_submissions', filters={'account_id': acc_id})
                if acc_submissions['data']:
                    submissions.extend(acc_submissions['data'])
        
        pending = len([s for s in submissions if s.get('status') == 'pending'])
        approved = len([s for s in submissions if s.get('status') == 'approved'])
        rejected = len([s for s in submissions if s.get('status') == 'rejected'])
        paid = len([s for s in submissions if s.get('status') == 'paid'])
        
        total_hours = sum(safe_float(s.get('hours')) for s in submissions)
        total_earnings = sum(safe_float(s.get('total_earnings_usd')) for s in submissions)
        
        stats = get_handshake_stats()
        
        return render_template('manager_dashboard.html', 
            accounts=accounts,
            submissions=submissions,
            pending=pending,
            approved=approved,
            rejected=rejected,
            paid=paid,
            total_hours=total_hours,
            total_earnings=total_earnings,
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=stats
        )
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return render_template('manager_dashboard.html', 
            accounts=[], 
            submissions=[], 
            pending=0,
            approved=0,
            rejected=0,
            paid=0,
            total_hours=0,
            total_earnings=0,
            user_name=session.get('user_name'), 
            now=datetime.now(), 
            stats=get_handshake_stats()
        )

# ============================================================
# WORKER DASHBOARD
# ============================================================

@app.route('/worker-dashboard')
@login_required
def worker_dashboard():
    user_id = session['user_id']
    user_name = session.get('user_name', 'Worker')
    user_email = session.get('user_email', 'worker@handshake.com')
    
    try:
        print("=" * 60)
        print("🔍 WORKER DASHBOARD DEBUG")
        print(f"👤 User ID: {user_id}")
        print("=" * 60)
        
        # Get assignments
        assignments_response = supabase_request('GET', 'hs_worker_assignments', filters={'worker_id': user_id})
        assignments = assignments_response['data'] if assignments_response['data'] else []
        print(f"📋 Assignments: {len(assignments)}")
        
        # Get all accounts
        accounts_response = supabase_request('GET', 'hs_accounts')
        all_accounts = accounts_response['data'] if accounts_response['data'] else []
        
        # Filter accounts assigned to this worker
        assigned_ids = [a['account_id'] for a in assignments]
        accounts = [acc for acc in all_accounts if acc['id'] in assigned_ids]
        print(f"📂 Accounts: {len(accounts)}")
        
        # Get ALL submissions
        submissions_response = supabase_request('GET', 'hs_submissions')
        all_submissions = submissions_response['data'] if submissions_response['data'] else []
        print(f"📝 Total Submissions in DB: {len(all_submissions)}")
        
        # Filter submissions by worker_id
        submissions = []
        for s in all_submissions:
            if s.get('worker_id') == user_id:
                submissions.append(s)
        
        print(f"📝 Submissions for this worker: {len(submissions)}")
        
        # Debug: Print submissions
        if len(submissions) == 0:
            print("   ⚠️ NO SUBMISSIONS FOUND")
        else:
            for idx, s in enumerate(submissions):
                print(f"  [{idx}] ID: {s.get('id')}, Status: {s.get('status')}, Hours: {s.get('hours')}, Payout: {s.get('worker_payout_usd')}")
        
        # Get settings
        settings = get_settings()
        exchange_rate = settings.get('exchange_rate', 150)
        
        # Initialize with 0 (not None)
        total_hours = 0.0
        total_earnings_usd = 0.0
        total_earnings_kes = 0.0
        pending_submissions = 0
        approved_submissions = 0
        rejected_submissions = 0
        paid_submissions = 0
        pending_payment_proofs = 0
        total_payment_proofs = 0
        
        # Process each submission
        for s in submissions:
            sub_type = s.get('submission_type', 'hours')
            status = s.get('status')
            
            hours_val = safe_float(s.get('hours', 0))
            worker_payout_usd = safe_float(s.get('worker_payout_usd', 0))
            
            # If payout is 0, try to calculate it
            if worker_payout_usd == 0:
                total_earnings = safe_float(s.get('total_earnings_usd', 0))
                worker_percentage = safe_float(s.get('worker_percentage', 10))
                if total_earnings > 0:
                    worker_payout_usd = total_earnings * (worker_percentage / 100)
                elif hours_val > 0:
                    account_id = s.get('account_id')
                    account = next((a for a in all_accounts if a.get('id') == account_id), None)
                    if account:
                        client_rate = safe_float(account.get('client_rate', 15))
                        total_earnings = hours_val * client_rate
                        worker_payout_usd = total_earnings * (worker_percentage / 100)
            
            worker_payout_kes = safe_float(s.get('worker_payout_kes', worker_payout_usd * exchange_rate))
            
            if sub_type == 'payment_proof':
                total_payment_proofs += 1
            
            if status == 'paid':
                paid_submissions += 1
                total_hours += hours_val
                total_earnings_usd += worker_payout_usd
                total_earnings_kes += worker_payout_kes
            elif status == 'approved':
                approved_submissions += 1
                total_hours += hours_val
                total_earnings_usd += worker_payout_usd
                total_earnings_kes += worker_payout_kes
            elif status == 'pending':
                pending_submissions += 1
                if sub_type == 'payment_proof':
                    pending_payment_proofs += 1
            elif status == 'rejected':
                rejected_submissions += 1
        
        # Make sure all values are numbers (not None)
        total_hours = float(total_hours or 0)
        total_earnings_usd = float(total_earnings_usd or 0)
        total_earnings_kes = float(total_earnings_kes or 0)
        
        print("=" * 60)
        print(f"📊 FINAL TOTALS: Hours={total_hours}, USD=${total_earnings_usd}, KES=KSh{total_earnings_kes}")
        print("=" * 60)
        
        # Add account names to submissions
        account_dict = {acc['id']: acc for acc in all_accounts}
        for s in submissions:
            acc = account_dict.get(s.get('account_id'))
            s['account_name'] = safe_str(acc.get('name', 'Unknown') if acc else 'Unknown')
        
        stats = get_handshake_stats()
        
        return render_template('worker_dashboard.html',
            accounts=accounts,
            submissions=submissions,
            total_hours=total_hours,
            total_earnings_usd=total_earnings_usd,
            total_earnings_kes=total_earnings_kes,
            pending_submissions=pending_submissions,
            approved_submissions=approved_submissions,
            rejected_submissions=rejected_submissions,
            paid_submissions=paid_submissions,
            pending_payment_proofs=pending_payment_proofs,
            total_payment_proofs=total_payment_proofs,
            exchange_rate=exchange_rate,
            settings_updated=settings.get('updated_at', 'N/A')[:10] if settings.get('updated_at') else 'N/A',
            user_name=user_name,
            user_email=user_email,
            now=datetime.now(),
            stats=stats
        )
        
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Error loading worker dashboard: {str(e)}', 'danger')
        return render_template('worker_dashboard.html',
            accounts=[],
            submissions=[], 
            total_hours=0,
            total_earnings_usd=0,
            total_earnings_kes=0,
            pending_submissions=0,
            approved_submissions=0,
            rejected_submissions=0,
            paid_submissions=0,
            pending_payment_proofs=0,
            total_payment_proofs=0,
            exchange_rate=150,
            settings_updated='N/A',
            user_name=user_name,
            user_email=user_email,
            now=datetime.now(), 
            stats=get_handshake_stats()
        )
# ============================================================
# SUBMIT HOURS
# ============================================================

@app.route('/submit-hours')
@login_required
def submit_hours():
    user_id = session['user_id']
    user_name = session.get('user_name', 'Worker')
    user_email = session.get('user_email', 'worker@handshake.com')
    
    try:
        assignments_response = supabase_request('GET', 'hs_worker_assignments', filters={'worker_id': user_id})
        assignments = assignments_response['data'] if assignments_response['data'] else []
        
        accounts_response = supabase_request('GET', 'hs_accounts')
        all_accounts = accounts_response['data'] if accounts_response['data'] else []
        
        assigned_ids = []
        for a in assignments:
            assigned_ids.append(a['account_id'])
        
        accounts = []
        for acc in all_accounts:
            if acc['id'] in assigned_ids:
                accounts.append(acc)
        
        submissions_response = supabase_request('GET', 'hs_submissions', filters={'worker_id': user_id})
        submissions = submissions_response['data'] if submissions_response['data'] else []
        
        account_dict = {acc['id']: acc for acc in all_accounts}
        for s in submissions:
            acc = account_dict.get(s.get('account_id'))
            s['account_name'] = safe_str(acc.get('name', 'Unknown') if acc else 'Unknown')
        
        return render_template('submit_hours.html',
            accounts=accounts,
            submissions=submissions[:10],
            user_name=user_name,
            user_email=user_email,
            user_id=user_id,
            now=datetime.now()
        )
        
    except Exception as e:
        print(f"❌ ERROR in submit_hours: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Error loading submit page: {str(e)}', 'danger')
        return render_template('submit_hours.html',
            accounts=[],
            submissions=[],
            user_name=user_name,
            user_email=user_email,
            user_id=user_id,
            now=datetime.now()
        )

# ============================================================
# API SUBMIT HOURS
# ============================================================

@app.route('/api/submit-hours', methods=['POST'])
@login_required
def api_submit_hours():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        user_id = session.get('user_id')
        account_id = data.get('account_id')
        date = data.get('date')
        hours = data.get('hours')
        screenshot_url = data.get('screenshot_url')
        notes = data.get('notes', '')
        
        if not account_id:
            return jsonify({'success': False, 'error': 'Account ID required'}), 400
        if not date:
            return jsonify({'success': False, 'error': 'Date required'}), 400
        if not hours or hours <= 0:
            return jsonify({'success': False, 'error': 'Valid hours required'}), 400
        
        check_response = supabase_request('GET', 'hs_submissions', filters={
            'worker_id': user_id,
            'account_id': account_id,
            'date': date,
            'submission_type': 'hours'
        })
        
        if check_response['data'] and len(check_response['data']) > 0:
            return jsonify({
                'success': False, 
                'error': 'You already submitted hours for this account on this date'
            }), 400
        
        submission_data = {
            'id': str(uuid.uuid4()),
            'worker_id': user_id,
            'account_id': account_id,
            'date': date,
            'hours': hours,
            'screenshot_url': screenshot_url or '',
            'notes': notes or '',
            'submission_type': 'hours',
            'status': 'pending',
            'worker_payout_usd': 0,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        response = supabase_request('POST', 'hs_submissions', data=submission_data)
        
        if response.get('data'):
            return jsonify({
                'success': True,
                'message': 'Hours submitted successfully!',
                'submission_id': response['data'][0]['id'] if response['data'] else None
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to save submission'}), 500
            
    except Exception as e:
        print(f"❌ Error in api_submit_hours: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# API CHECK HOURS SUBMISSION
# ============================================================

@app.route('/api/check-hours-submission', methods=['GET'])
@login_required
def check_hours_submission():
    try:
        user_id = session['user_id']
        date = request.args.get('date')
        
        if not date:
            return jsonify({'exists': False})
        
        existing = supabase_request('GET', 'hs_submissions', 
            filters={
                'worker_id': user_id,
                'submission_type': 'hours',
                'date': date
            }
        )
        
        return jsonify({
            'exists': len(existing['data']) > 0,
            'count': len(existing['data']) if existing['data'] else 0
        })
    except Exception as e:
        print(f"Error checking hours submission: {e}")
        return jsonify({'exists': False})

# ============================================================
# API CHECK PAYMENT SUBMISSION
# ============================================================

@app.route('/api/check-payment-submission', methods=['GET'])
@login_required
def check_payment_submission():
    try:
        user_id = session['user_id']
        date_str = request.args.get('date')
        
        if not date_str:
            return jsonify({'exists': False})
        
        try:
            submission_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except:
            submission_date = datetime.utcnow().date()
        
        existing = supabase_request('GET', 'hs_submissions', 
            filters={
                'worker_id': user_id,
                'submission_type': 'payment_proof'
            }
        )
        
        if existing['data']:
            for payment in existing['data']:
                if payment.get('status') == 'rejected':
                    continue
                    
                payment_date_str = payment.get('date')
                if payment_date_str:
                    try:
                        p_date = datetime.strptime(payment_date_str, '%Y-%m-%d').date()
                        days_diff = abs((submission_date - p_date).days)
                        
                        if days_diff <= 7:
                            return jsonify({
                                'exists': True, 
                                'last_submission': payment_date_str,
                                'days_ago': days_diff,
                                'message': f'You submitted a payment proof on {payment_date_str} ({days_diff} days ago). Must wait 7 days between submissions.'
                            })
                    except:
                        pass
        
        return jsonify({'exists': False})
    except Exception as e:
        print(f"Error checking payment submission: {e}")
        return jsonify({'exists': False})

# ============================================================
# API SUBMIT PAYMENT PROOF
# ============================================================

@app.route('/api/submit-payment-proof', methods=['POST'])
@login_required
def api_submit_payment_proof():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        user_id = session.get('user_id')
        account_id = data.get('account_id')
        date = data.get('date')
        payment_reference = data.get('payment_reference', 'N/A')
        payment_amount = data.get('payment_amount')
        payment_proof_url = data.get('payment_proof_url')
        
        if not account_id:
            return jsonify({'success': False, 'error': 'Account ID required'}), 400
        if not date:
            return jsonify({'success': False, 'error': 'Date required'}), 400
        if not payment_amount or payment_amount <= 0:
            return jsonify({'success': False, 'error': 'Valid payment amount required'}), 400
        if not payment_proof_url:
            return jsonify({'success': False, 'error': 'Payment proof screenshot required'}), 400
        
        check_response = supabase_request('GET', 'hs_submissions', filters={
            'worker_id': user_id,
            'account_id': account_id,
            'submission_type': 'payment_proof'
        })
        
        try:
            new_date = datetime.strptime(date, '%Y-%m-%d').date()
        except:
            new_date = datetime.utcnow().date()
        
        if check_response['data']:
            for sub in check_response['data']:
                if sub.get('status') == 'rejected':
                    continue
                
                sub_date_str = sub.get('date')
                if sub_date_str:
                    try:
                        sub_date = datetime.strptime(sub_date_str, '%Y-%m-%d').date()
                        days_diff = abs((new_date - sub_date).days)
                        
                        if days_diff <= 7:
                            return jsonify({
                                'success': False,
                                'error': f'❌ You already submitted a payment proof on {sub_date_str}. Must wait 7 days between submissions. (Days difference: {days_diff})'
                            }), 400
                    except:
                        pass
        
        worker_result = supabase_request('GET', 'hs_users', filters={'id': user_id})
        worker_percentage = safe_float(worker_result['data'][0].get('worker_percentage', 10)) if worker_result['data'] else 10
        
        account_result = supabase_request('GET', 'hs_accounts', filters={'id': account_id})
        client_rate = safe_float(account_result['data'][0].get('client_rate', 15)) if account_result['data'] else 15
        
        settings = get_settings()
        exchange_rate = settings.get('exchange_rate', 150)
        
        payment_amount = safe_float(payment_amount)
        worker_payout = payment_amount * (worker_percentage / 100)
        your_revenue = payment_amount - worker_payout
        
        submission_data = {
            'id': str(uuid.uuid4()),
            'worker_id': user_id,
            'account_id': account_id,
            'date': date,
            'hours': 0,
            'screenshot_url': payment_proof_url,
            'notes': f"Payment Ref: {payment_reference} | Amount: ${payment_amount:.2f} | Worker Share: {worker_percentage}%",
            'submission_type': 'payment_proof',
            'status': 'pending',
            'client_rate': client_rate,
            'worker_percentage': worker_percentage,
            'total_earnings_usd': payment_amount,
            'commission_usd': your_revenue,
            'worker_payout_usd': worker_payout,
            'worker_payout_kes': worker_payout * exchange_rate,
            'payment_proof_url': payment_proof_url,
            'payment_reference': payment_reference,
            'payment_confirmed': False,
            'payment_proof_uploaded_at': datetime.utcnow().isoformat(),
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        response = supabase_request('POST', 'hs_submissions', data=submission_data)
        
        if response.get('data'):
            return jsonify({
                'success': True,
                'message': f'✅ Payment proof submitted successfully! You will earn ${worker_payout:.2f} ({worker_percentage}%)',
                'submission_id': response['data'][0]['id'] if response['data'] else None
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to save payment proof'}), 500
            
    except Exception as e:
        print(f"❌ Error in api_submit_payment_proof: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# API UPLOAD
# ============================================================

@app.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        from werkzeug.utils import secure_filename
        import uuid
        
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        
        bucket_name = 'uploads'
        
        # Read file content
        file_content = file.read()
        
        # Upload to Supabase Storage using public endpoint
        url = f"{SUPABASE_URL}/storage/v1/object/public/{bucket_name}/{unique_filename}"
        
        headers = {
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': file.content_type or 'application/octet-stream'
        }
        
        print(f"📤 Uploading to: {url}")
        print(f"📤 File size: {len(file_content)} bytes")
        
        response = requests.post(url, headers=headers, data=file_content)
        
        print(f"📤 Response status: {response.status_code}")
        
        if response.status_code in [200, 201, 204]:
            file_url = f"{SUPABASE_URL}/storage/v1/object/public/{bucket_name}/{unique_filename}"
            return jsonify({
                'success': True,
                'url': file_url,
                'filename': unique_filename
            })
        else:
            # Try alternative endpoint
            alt_url = f"{SUPABASE_URL}/storage/v1/object/{bucket_name}/{unique_filename}"
            alt_response = requests.post(alt_url, headers=headers, data=file_content)
            
            if alt_response.status_code in [200, 201, 204]:
                file_url = f"{SUPABASE_URL}/storage/v1/object/public/{bucket_name}/{unique_filename}"
                return jsonify({
                    'success': True,
                    'url': file_url,
                    'filename': unique_filename
                })
            else:
                return jsonify({
                    'success': False,
                    'error': f'Upload failed: {response.status_code} - {response.text[:100]}'
                }), 500
                
    except Exception as e:
        print(f"❌ Error in api_upload: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# MY SUBMISSIONS
# ============================================================

@app.route('/my-submissions')
@login_required
def my_submissions():
    user_id = session['user_id']
    
    try:
        account_dict, worker_dict, _, _ = build_lookups()
        
        submissions_data = supabase_request('GET', 'hs_submissions', filters={'worker_id': user_id})
        if submissions_data['data']:
            for s in submissions_data['data']:
                account = account_dict.get(s.get('account_id'))
                s['account_name'] = safe_str(account.get('name', 'Unknown') if account else 'Unknown')
                s['hours'] = safe_float(s.get('hours'))
                s['total_earnings_usd'] = safe_float(s.get('total_earnings_usd'))
                s['worker_payout_usd'] = safe_float(s.get('worker_payout_usd'))
        
        return render_template('my_submissions.html', 
            submissions=submissions_data['data'] if submissions_data['data'] else [],
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return render_template('my_submissions.html', submissions=[], user_name=session.get('user_name'), now=datetime.now(), stats=get_handshake_stats())

# ============================================================
# APPROVALS
# ============================================================

@app.route('/approvals')
@login_required
@manager_required
def approvals():
    user_id = session['user_id']
    user_role = session.get('user_role', 'worker')
    
    try:
        account_dict, worker_dict, _, _ = build_lookups()
        
        submissions_data = supabase_request('GET', 'hs_submissions', filters={'status': 'pending'})
        
        submissions = []
        if submissions_data['data']:
            for s in submissions_data['data']:
                worker = worker_dict.get(s.get('worker_id'))
                s['worker_name'] = safe_str(worker.get('name', 'Unknown') if worker else 'Unknown')
                
                account = account_dict.get(s.get('account_id'))
                s['account_name'] = safe_str(account.get('name', 'Unknown') if account else 'Unknown')
                
                s['submission_type'] = s.get('submission_type', 'hours')
                s['hours'] = safe_float(s.get('hours'))
                s['total_earnings_usd'] = safe_float(s.get('total_earnings_usd'))
                s['worker_payout_usd'] = safe_float(s.get('worker_payout_usd'))
                s['commission_usd'] = safe_float(s.get('commission_usd'))
                s['date'] = safe_str(s.get('date'), 'N/A')
                s['screenshot_url'] = safe_str(s.get('screenshot_url'))
                s['payment_reference'] = safe_str(s.get('payment_reference'), 'N/A')
                
                submissions.append(s)
        
        return render_template('approvals.html', 
            submissions=submissions,
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )
    except Exception as e:
        print(f"❌ ERROR in approvals route: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Error: {str(e)}', 'danger')
        return render_template('approvals.html', submissions=[], user_name=session.get('user_name'), now=datetime.now(), stats=get_handshake_stats())

# ============================================================
# API APPROVALS
# ============================================================

@app.route('/api/approvals', methods=['PATCH'])
@login_required
@admin_required
def api_approvals():
    try:
        data = request.get_json()
        
        if not data or 'id' not in data or 'status' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing required fields',
                'message': 'id and status are required'
            }), 400
        
        submission_id = data.get('id')
        status = data.get('status')
        notes = data.get('notes', '')
        admin_id = session.get('user_id')
        admin_name = session.get('user_name', 'Admin')
        
        if status not in ['approved', 'rejected']:
            return jsonify({
                'success': False,
                'error': 'Invalid status',
                'message': 'Status must be approved or rejected'
            }), 400
        
        submission = supabase_request('GET', 'hs_submissions', filters={'id': submission_id})
        if not submission['data']:
            return jsonify({
                'success': False,
                'error': 'Submission not found'
            }), 404
        
        submission_data = submission['data'][0]
        submission_type = submission_data.get('submission_type', 'hours')
        worker_id = submission_data.get('worker_id')
        
        update_data = {
            'status': status,
            'notes': notes,
            'approved_by': admin_name,
            'approved_by_id': admin_id,
            'approved_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        # Payment proof approval - Credit the worker
        if submission_type == 'payment_proof' and status == 'approved':
            worker_payout = safe_float(submission_data.get('worker_payout_usd'))
            
            update_data['status'] = 'paid'
            update_data['payment_confirmed'] = True
            update_data['payment_confirmed_by'] = admin_id
            update_data['payment_confirmed_by_name'] = admin_name
            update_data['payment_confirmed_at'] = datetime.utcnow().isoformat()
            update_data['paid_at'] = datetime.utcnow().isoformat()
            
            result = supabase_request('PATCH', 'hs_submissions', data=update_data, filters={'id': submission_id})
            
            if worker_id and worker_payout > 0:
                try:
                    worker_result = supabase_request('GET', 'hs_users', filters={'id': worker_id})
                    if worker_result['data']:
                        worker = worker_result['data'][0]
                        current_balance = safe_float(worker.get('total_earnings_usd', 0))
                        current_payout = safe_float(worker.get('total_payout_usd', 0))
                        
                        worker_update = {
                            'total_earnings_usd': current_balance + worker_payout,
                            'total_payout_usd': current_payout + worker_payout,
                            'updated_at': datetime.utcnow().isoformat()
                        }
                        
                        supabase_request('PATCH', 'hs_users', data=worker_update, filters={'id': worker_id})
                except Exception as e:
                    print(f"⚠️ Error updating worker balance: {e}")
            
            return jsonify({
                'success': True,
                'message': f'✅ Payment approved! ${worker_payout:.2f} credited to worker.',
                'submission_id': submission_id,
                'status': 'paid',
                'worker_payout': worker_payout,
                'notes': notes,
                'approved_by': admin_name,
                'approved_at': datetime.utcnow().isoformat()
            }), 200
        
        # Hours approval
        elif submission_type == 'hours':
            result = supabase_request('PATCH', 'hs_submissions', data=update_data, filters={'id': submission_id})
            
            return jsonify({
                'success': True,
                'message': f'✅ Hours submission {status} successfully',
                'submission_id': submission_id,
                'status': status,
                'notes': notes,
                'approved_by': admin_name,
                'approved_at': datetime.utcnow().isoformat()
            }), 200
        
        else:
            result = supabase_request('PATCH', 'hs_submissions', data=update_data, filters={'id': submission_id})
            return jsonify({
                'success': True,
                'message': f'✅ Submission {status} successfully',
                'submission_id': submission_id,
                'status': status,
                'notes': notes,
                'approved_by': admin_name,
                'approved_at': datetime.utcnow().isoformat()
            }), 200
        
    except Exception as e:
        print(f"❌ Error in api_approvals: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'Server error',
            'message': str(e)
        }), 500

# ============================================================
# API CONFIRM PAYMENT
# ============================================================

@app.route('/api/confirm-payment', methods=['POST'])
@login_required
@admin_required
def confirm_payment():
    try:
        data = request.get_json()
        
        if not data or 'submission_id' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing submission_id'
            }), 400
        
        submission_id = data.get('submission_id')
        admin_name = session.get('user_name', 'Admin')
        admin_id = session.get('user_id')
        
        submission = supabase_request('GET', 'hs_submissions', filters={'id': submission_id})
        if not submission['data']:
            return jsonify({
                'success': False,
                'error': 'Submission not found'
            }), 404
        
        if submission['data'][0].get('submission_type') != 'payment_proof':
            return jsonify({
                'success': False,
                'error': 'Only payment proofs can be confirmed'
            }), 400
        
        worker_payout_usd = safe_float(submission['data'][0].get('worker_payout_usd'))
        worker_id = submission['data'][0].get('worker_id')
        
        settings = get_settings()
        exchange_rate = settings.get('exchange_rate', 150)
        worker_payout_kes = worker_payout_usd * exchange_rate
        
        # Update submission to paid
        update_data = {
            'payment_confirmed': True,
            'payment_confirmed_by': admin_id,
            'payment_confirmed_by_name': admin_name,
            'payment_confirmed_at': datetime.utcnow().isoformat(),
            'status': 'paid',
            'updated_at': datetime.utcnow().isoformat()
        }
        
        # Try to add KES fields if they exist
        try:
            update_data['exchange_rate_used'] = exchange_rate
            update_data['worker_payout_kes'] = worker_payout_kes
        except:
            pass
        
        result = supabase_request('PATCH', 'hs_submissions', data=update_data, filters={'id': submission_id})
        
        # Update worker earnings
        if worker_id and worker_payout_usd > 0:
            try:
                worker_result = supabase_request('GET', 'hs_users', filters={'id': worker_id})
                if worker_result['data']:
                    worker = worker_result['data'][0]
                    
                    worker_update = {'updated_at': datetime.utcnow().isoformat()}
                    
                    try:
                        current = safe_float(worker.get('total_earnings_usd', 0))
                        worker_update['total_earnings_usd'] = current + worker_payout_usd
                    except:
                        pass
                    
                    try:
                        current = safe_float(worker.get('total_payout_usd', 0))
                        worker_update['total_payout_usd'] = current + worker_payout_usd
                    except:
                        pass
                    
                    try:
                        current = safe_float(worker.get('total_earnings_kes', 0))
                        worker_update['total_earnings_kes'] = current + worker_payout_kes
                    except:
                        pass
                    
                    try:
                        current = safe_float(worker.get('total_payout_kes', 0))
                        worker_update['total_payout_kes'] = current + worker_payout_kes
                    except:
                        pass
                    
                    if len(worker_update) > 1:
                        supabase_request('PATCH', 'hs_users', data=worker_update, filters={'id': worker_id})
                        
            except Exception as e:
                print(f"⚠️ Error updating worker: {e}")
        
        return jsonify({
            'success': True,
            'message': f'✅ Payment confirmed! ${worker_payout_usd:.2f} (KSh {worker_payout_kes:,.2f})',
            'submission_id': submission_id,
            'confirmed_by': admin_name,
            'confirmed_at': datetime.utcnow().isoformat(),
            'exchange_rate': exchange_rate,
            'usd_amount': worker_payout_usd,
            'kes_amount': worker_payout_kes
        }), 200
        
    except Exception as e:
        print(f"❌ Error in confirm_payment: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'message': 'Server error: ' + str(e)
        }), 500

# ============================================================
# API REJECT PAYMENT PROOF
# ============================================================

@app.route('/api/reject-payment-proof', methods=['POST'])
@login_required
@admin_required
def reject_payment_proof():
    try:
        data = request.get_json()
        
        if not data or 'submission_id' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing submission_id'
            }), 400
        
        submission_id = data.get('submission_id')
        reason = data.get('reason', 'Rejected by admin')
        admin_name = session.get('user_name', 'Admin')
        admin_id = session.get('user_id')
        
        submission = supabase_request('GET', 'hs_submissions', filters={'id': submission_id})
        if not submission['data']:
            return jsonify({
                'success': False,
                'error': 'Submission not found'
            }), 404
        
        if submission['data'][0].get('submission_type') != 'payment_proof':
            return jsonify({
                'success': False,
                'error': 'Only payment proofs can be rejected'
            }), 400
        
        update_data = {
            'status': 'rejected',
            'payment_confirmed': False,
            'payment_rejection_reason': reason,
            'payment_rejected_by': admin_id,
            'payment_rejected_by_name': admin_name,
            'payment_rejected_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        result = supabase_request('PATCH', 'hs_submissions', data=update_data, filters={'id': submission_id})
        
        return jsonify({
            'success': True,
            'message': '❌ Payment rejected successfully',
            'submission_id': submission_id,
            'reason': reason,
            'rejected_by': admin_name,
            'rejected_at': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        print(f"❌ Error in reject_payment_proof: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'Server error',
            'message': str(e)
        }), 500

# ============================================================
# PAYMENTS
# ============================================================

@app.route('/payments')
@login_required
@admin_required
def payments():
    try:
        account_dict, worker_dict, _, _ = build_lookups()
        submissions_data = supabase_request('GET', 'hs_submissions')
        settings = get_settings()
        exchange_rate = settings.get('exchange_rate', 150)
        
        pending_proofs = []
        confirmed_payments = []
        total_paid = 0
        total_pending = 0
        total_amount_paid = 0
        total_amount_pending = 0
        total_amount_paid_kes = 0
        total_amount_pending_kes = 0
        
        if submissions_data['data']:
            for s in submissions_data['data']:
                if s.get('submission_type') != 'payment_proof':
                    continue
                
                worker = worker_dict.get(s.get('worker_id'))
                worker_name = safe_str(worker.get('name', 'Unknown') if worker else 'Unknown')
                
                account = account_dict.get(s.get('account_id'))
                account_name = safe_str(account.get('name', 'Unknown') if account else 'Unknown')
                
                amount = safe_float(s.get('total_earnings_usd'))
                worker_payout = safe_float(s.get('worker_payout_usd'))
                
                amount_kes = amount * exchange_rate
                payout_kes = worker_payout * exchange_rate
                
                payment_data = {
                    'id': s.get('id'),
                    'worker_id': s.get('worker_id'),
                    'worker_name': worker_name,
                    'account_name': account_name,
                    'date': s.get('date'),
                    'payment_reference': safe_str(s.get('payment_reference', 'N/A')),
                    'payment_proof_url': safe_str(s.get('payment_proof_url')),
                    'payment_confirmed': s.get('payment_confirmed', False),
                    'status': s.get('status', 'pending'),
                    'amount': amount,
                    'amount_kes': amount_kes,
                    'worker_payout': worker_payout,
                    'worker_payout_kes': payout_kes,
                    'commission': safe_float(s.get('commission_usd'))
                }
                
                if s.get('payment_confirmed') and s.get('status') == 'paid':
                    confirmed_payments.append(payment_data)
                    total_paid += 1
                    total_amount_paid += amount
                    total_amount_paid_kes += amount_kes
                else:
                    pending_proofs.append(payment_data)
                    total_pending += 1
                    total_amount_pending += amount
                    total_amount_pending_kes += amount_kes
        
        return render_template('payments.html',
            pending_proofs=pending_proofs,
            confirmed_payments=confirmed_payments,
            total_paid=total_paid,
            total_pending=total_pending,
            total_amount_paid=total_amount_paid,
            total_amount_pending=total_amount_pending,
            total_amount_paid_kes=total_amount_paid_kes,
            total_amount_pending_kes=total_amount_pending_kes,
            exchange_rate=exchange_rate,
            settings_updated=settings.get('updated_at', 'Today')[:10] if settings.get('updated_at') else 'Today',
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )
    except Exception as e:
        print(f"❌ Error in payments: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Error: {str(e)}', 'danger')
        return render_template('payments.html',
            pending_proofs=[],
            confirmed_payments=[],
            total_paid=0,
            total_pending=0,
            total_amount_paid=0,
            total_amount_pending=0,
            total_amount_paid_kes=0,
            total_amount_pending_kes=0,
            exchange_rate=150,
            settings_updated='Today',
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )

# ============================================================
# REPORTS
# ============================================================

@app.route('/reports')
@login_required
@admin_required
def reports():
    try:
        account_dict, worker_dict, _, _ = build_lookups()
        
        submissions_data = supabase_request('GET', 'hs_submissions')
        
        account_hours = {}
        worker_earnings = {}
        account_revenue = {}
        payment_proofs = []
        total_hours = 0
        total_worker_payout = 0
        total_payment_amount = 0
        total_commission = 0
        
        today = datetime.utcnow().date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)
        
        weekly_hours = 0
        weekly_earnings = 0
        monthly_hours = 0
        monthly_earnings = 0
        
        if submissions_data['data']:
            for s in submissions_data['data']:
                submission_type = s.get('submission_type', 'hours')
                status = s.get('status')
                
                if status == 'rejected':
                    continue
                
                submission_date = None
                if s.get('date'):
                    try:
                        submission_date = datetime.strptime(s.get('date'), '%Y-%m-%d').date()
                    except:
                        pass
                
                if submission_type == 'hours':
                    account_id = s.get('account_id')
                    worker_id = s.get('worker_id')
                    hours = safe_float(s.get('hours'))
                    payout = safe_float(s.get('worker_payout_usd'))
                    commission = safe_float(s.get('commission_usd'))
                    total_earnings = safe_float(s.get('total_earnings_usd'))
                    
                    if account_id:
                        account_hours[account_id] = account_hours.get(account_id, 0) + hours
                        account_revenue[account_id] = account_revenue.get(account_id, 0) + (commission or (total_earnings - payout))
                    
                    if worker_id:
                        if worker_id not in worker_earnings:
                            worker_earnings[worker_id] = {'payout': 0, 'hours': 0, 'submissions': 0, 'commission': 0}
                        worker_earnings[worker_id]['payout'] += payout
                        worker_earnings[worker_id]['hours'] += hours
                        worker_earnings[worker_id]['submissions'] += 1
                        worker_earnings[worker_id]['commission'] += commission or (total_earnings - payout)
                        
                        total_hours += hours
                        total_worker_payout += payout
                        total_commission += commission or (total_earnings - payout)
                        
                        if submission_date:
                            if submission_date >= week_ago:
                                weekly_hours += hours
                                weekly_earnings += payout
                            if submission_date >= month_ago:
                                monthly_hours += hours
                                monthly_earnings += payout
                
                elif submission_type == 'payment_proof':
                    worker_id = s.get('worker_id')
                    amount = safe_float(s.get('total_earnings_usd'))
                    worker_payout = safe_float(s.get('worker_payout_usd'))
                    commission = safe_float(s.get('commission_usd'))
                    
                    if worker_id:
                        if worker_id not in worker_earnings:
                            worker_earnings[worker_id] = {'payout': 0, 'hours': 0, 'submissions': 0, 'commission': 0}
                        worker_earnings[worker_id]['payout'] += worker_payout
                        worker_earnings[worker_id]['submissions'] += 1
                        worker_earnings[worker_id]['commission'] += commission or (amount - worker_payout)
                        
                        total_worker_payout += worker_payout
                        total_commission += commission or (amount - worker_payout)
                    
                    total_payment_amount += amount
                    
                    payment_proofs.append({
                        'worker_id': worker_id,
                        'amount': amount,
                        'worker_payout': worker_payout,
                        'commission': commission or (amount - worker_payout),
                        'date': s.get('date'),
                        'reference': safe_str(s.get('payment_reference', 'N/A')),
                        'status': status
                    })
        
        account_names = {aid: safe_str(acc.get('name', 'Unknown')) for aid, acc in account_dict.items()}
        worker_names = {wid: safe_str(w.get('name', 'Unknown')) for wid, w in worker_dict.items()}
        
        top_workers = sorted(worker_earnings.items(), key=lambda x: x[1]['hours'], reverse=True)[:10]
        top_earners = sorted(worker_earnings.items(), key=lambda x: x[1]['payout'], reverse=True)[:10]
        
        return render_template('reports.html',
            account_hours=account_hours,
            account_names=account_names,
            account_revenue=account_revenue,
            worker_earnings=worker_earnings,
            worker_names=worker_names,
            payment_proofs=payment_proofs,
            total_hours=total_hours,
            total_worker_payout=total_worker_payout,
            total_commission=total_commission,
            total_payment_proofs=len(payment_proofs),
            total_payment_amount=total_payment_amount,
            weekly_hours=weekly_hours,
            weekly_earnings=weekly_earnings,
            monthly_hours=monthly_hours,
            monthly_earnings=monthly_earnings,
            top_workers=top_workers,
            top_earners=top_earners,
            submissions=submissions_data['data'] if submissions_data['data'] else [],
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )
    except Exception as e:
        print(f"❌ Error in reports: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Error: {str(e)}', 'danger')
        return render_template('reports.html', 
            account_hours={}, 
            account_names={},
            account_revenue={},
            worker_earnings={},
            worker_names={},
            payment_proofs=[],
            total_hours=0,
            total_worker_payout=0,
            total_commission=0,
            total_payment_proofs=0,
            total_payment_amount=0,
            weekly_hours=0,
            weekly_earnings=0,
            monthly_hours=0,
            monthly_earnings=0,
            top_workers=[],
            top_earners=[],
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )

# ============================================================
# SETTINGS
# ============================================================

@app.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    if request.method == 'POST':
        try:
            exchange_rate = safe_float(request.form.get('exchange_rate', 150))
            default_worker_percentage = safe_float(request.form.get('default_worker_percentage', 10))
            default_hourly_rate = safe_float(request.form.get('default_hourly_rate', 10))
            default_client_rate = safe_float(request.form.get('default_client_rate', 15))
            
            existing = supabase_request('GET', 'hs_settings')
            
            settings_data = {
                'exchange_rate': exchange_rate,
                'default_worker_percentage': default_worker_percentage,
                'default_hourly_rate': default_hourly_rate,
                'default_client_rate': default_client_rate,
                'updated_at': datetime.utcnow().isoformat()
            }
            
            if existing['data'] and len(existing['data']) > 0:
                supabase_request('PATCH', 'hs_settings', 
                    data=settings_data,
                    filters={'id': existing['data'][0]['id']}
                )
            else:
                settings_data['id'] = str(uuid.uuid4())
                settings_data['created_at'] = datetime.utcnow().isoformat()
                supabase_request('POST', 'hs_settings', data=settings_data)
            
            flash('Settings updated successfully!', 'success')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
    
    settings_data = get_settings()
    return render_template('settings.html', 
        settings=settings_data,
        user_name=session.get('user_name'),
        now=datetime.now(),
        stats=get_handshake_stats()
    )

# ============================================================
# ACCOUNTS
# ============================================================

@app.route('/accounts')
@login_required
@admin_required
def accounts():
    try:
        accounts_data = supabase_request('GET', 'hs_accounts')
        proxies_data = supabase_request('GET', 'hs_proxies')
        return render_template('accounts.html', 
            accounts=accounts_data['data'] if accounts_data['data'] else [],
            proxies=proxies_data['data'] if proxies_data['data'] else [],
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return render_template('accounts.html', accounts=[], proxies=[], user_name=session.get('user_name'), now=datetime.now(), stats=get_handshake_stats())

@app.route('/api/accounts', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
@admin_required
def api_accounts():
    if request.method == 'GET':
        try:
            result = supabase_request('GET', 'hs_accounts')
            return jsonify({'success': True, 'data': result['data']})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
   elif request.method == 'POST':
    try:
        user_role = session.get('user_role', 'worker')
        user_id = session.get('user_id')
        user_name = session.get('user_name', 'User')
        user_email = session.get('user_email', '')
        
        data = request.get_json()
        
        # Required fields
        if not data.get('title'):
            return jsonify({'success': False, 'error': 'Title is required'}), 400
        if not data.get('message'):
            return jsonify({'success': False, 'error': 'Message is required'}), 400
        
        # ============================================================
        # 🔥🔥🔥 FORCE ADMIN PERMISSIONS
        # ============================================================
        admin_emails = ['admin@handshake.com', 'admin@example.com']
        if user_email in admin_emails:
            user_role = 'admin'
            session['user_role'] = 'admin'
        
        # Also check database
        if user_id:
            try:
                user_check = supabase_request('GET', 'hs_users', filters={'id': user_id})
                if user_check['data']:
                    db_user = user_check['data'][0]
                    if db_user.get('role') == 'admin':
                        user_role = 'admin'
                        session['user_role'] = 'admin'
            except:
                pass
        
        print(f"✅ User: {user_name} ({user_role}) - {user_email}")
        
        # ============================================================
        # 🔥 RECIPIENT MAPPING - ACCEPT BOTH FORMATS
        # ============================================================
        recipient_type = data.get('recipient_type', 'all_users')
        
        # 🔥 FIX: Accept both formats
        if recipient_type == 'workers':
            recipient_type = 'all_workers'
        elif recipient_type == 'admins':
            recipient_type = 'all_admins'
        elif recipient_type == 'all':
            recipient_type = 'all_users'
        
        # ============================================================
        # 🔥 PERMISSION CHECK
        # ============================================================
        allowed_recipients = []
        
        if user_role == 'admin':
            allowed_recipients = ['all_workers', 'all_admins', 'all_users', 'specific_worker', 'specific_admin']
        else:
            allowed_recipients = ['all_workers', 'all_users', 'specific_worker']
            if recipient_type in ['all_admins', 'specific_admin']:
                return jsonify({
                    'success': False, 
                    'error': '❌ Workers cannot send messages to admins'
                }), 403
        
        if recipient_type not in allowed_recipients:
            return jsonify({
                'success': False, 
                'error': f'❌ You are not allowed to send to: {recipient_type}'
            }), 403
        
        # ============================================================
        # 🔥 MAP RECIPIENT TO AUDIENCE
        # ============================================================
        audience_map = {
            'all_workers': 'workers',
            'all_admins': 'admins',
            'all_users': 'all',
            'specific_worker': 'workers',
            'specific_admin': 'admins'
        }
        audience = audience_map.get(recipient_type, 'all')
        
        # ============================================================
        # 🔥 GET TARGET USERS
        # ============================================================
        target_users = []
        
        if recipient_type == 'all_workers':
            try:
                users_response = supabase_request('GET', 'hs_users', filters={'role': 'worker'})
                if users_response['data']:
                    target_users = [u['id'] for u in users_response['data']]
            except Exception as e:
                print(f"⚠️ Error getting workers: {e}")
                
        elif recipient_type == 'all_admins':
            try:
                users_response = supabase_request('GET', 'hs_users', filters={'role': 'admin'})
                if users_response['data']:
                    target_users = [u['id'] for u in users_response['data']]
            except Exception as e:
                print(f"⚠️ Error getting admins: {e}")
                
        elif recipient_type == 'all_users':
            try:
                users_response = supabase_request('GET', 'hs_users')
                if users_response['data']:
                    target_users = [u['id'] for u in users_response['data']]
            except Exception as e:
                print(f"⚠️ Error getting all users: {e}")
                
        elif recipient_type in ['specific_worker', 'specific_admin']:
            recipient_id = data.get('recipient_id')
            if recipient_id:
                target_users = [recipient_id]
        
        # ============================================================
        # 🔥 BUILD ANNOUNCEMENT DATA
        # ============================================================
        announcement_data = {
            'id': str(uuid.uuid4()),
            'title': data.get('title'),
            'message': data.get('message'),
            'audience': audience,
            'priority': data.get('priority', 'normal'),
            'target_users': json.dumps(target_users),
            'read_by': json.dumps([]),
            'created_by': user_id,
            'created_by_name': user_name,
            'created_by_role': user_role,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        result = supabase_request('POST', 'hs_announcements', data=announcement_data)
        
        if result.get('data'):
            return jsonify({
                'success': True,
                'data': result['data'],
                'message': '✅ Announcement sent successfully!',
                'audience': audience,
                'target_count': len(target_users)
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to create announcement'}), 500
            
    except Exception as e:
        print(f"❌ Error creating announcement: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# PROXIES
# ============================================================

@app.route('/proxies')
@login_required
@admin_required
def proxies():
    try:
        proxies_data = supabase_request('GET', 'hs_proxies')
        return render_template('proxies.html', 
            proxies=proxies_data['data'] if proxies_data['data'] else [],
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return render_template('proxies.html', proxies=[], user_name=session.get('user_name'), now=datetime.now(), stats=get_handshake_stats())

@app.route('/api/proxies', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
@admin_required
def api_proxies():
    if request.method == 'GET':
        try:
            result = supabase_request('GET', 'hs_proxies')
            return jsonify({'success': True, 'data': result['data']})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            proxy_data = {
                'id': str(uuid.uuid4()),
                'ip': data.get('ip'),
                'port': data.get('port'),
                'provider': data.get('provider'),
                'location': data.get('location'),
                'status': data.get('status', 'active'),
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }
            result = supabase_request('POST', 'hs_proxies', data=proxy_data)
            return jsonify({'success': True, 'data': result['data'], 'message': 'Proxy added successfully!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'PUT':
        try:
            data = request.get_json()
            proxy_id = data.get('id')
            if not proxy_id:
                return jsonify({'success': False, 'error': 'Proxy ID required'}), 400
            del data['id']
            data['updated_at'] = datetime.utcnow().isoformat()
            result = supabase_request('PATCH', 'hs_proxies', data=data, filters={'id': proxy_id})
            return jsonify({'success': True, 'data': result['data'], 'message': 'Proxy updated successfully!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'DELETE':
        try:
            proxy_id = request.args.get('id')
            if not proxy_id:
                return jsonify({'success': False, 'error': 'Proxy ID required'}), 400
            supabase_request('DELETE', 'hs_proxies', filters={'id': proxy_id})
            return jsonify({'success': True, 'message': 'Proxy deleted successfully!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# WORKERS
# ============================================================

@app.route('/workers')
@login_required
@admin_required
def workers():
    try:
        workers_data = supabase_request('GET', 'hs_users', filters={'role': 'worker'})
        accounts_data = supabase_request('GET', 'hs_accounts')
        assignments_data = supabase_request('GET', 'hs_worker_assignments')
        
        assignment_map = {}
        if assignments_data['data']:
            for a in assignments_data['data']:
                if a['worker_id'] not in assignment_map:
                    assignment_map[a['worker_id']] = []
                assignment_map[a['worker_id']].append(a['account_id'])
        
        workers_with_whatsapp = 0
        workers_without_whatsapp = 0
        
        if workers_data['data']:
            for w in workers_data['data']:
                w['assigned_accounts'] = assignment_map.get(w['id'], [])
                w['login_sent'] = w.get('account_login_sent', False)
                
                if w.get('whatsapp'):
                    workers_with_whatsapp += 1
                else:
                    workers_without_whatsapp += 1
        
        return render_template('workers.html', 
            workers=workers_data['data'] if workers_data['data'] else [],
            accounts=accounts_data['data'] if accounts_data['data'] else [],
            workers_with_whatsapp=workers_with_whatsapp,
            workers_without_whatsapp=workers_without_whatsapp,
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return render_template('workers.html', workers=[], accounts=[], user_name=session.get('user_name'), now=datetime.now(), stats=get_handshake_stats())

@app.route('/api/workers', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
@admin_required
def api_workers():
    if request.method == 'GET':
        try:
            result = supabase_request('GET', 'hs_users', filters={'role': 'worker'})
            return jsonify({'success': True, 'data': result['data']})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            worker_data = {
                'id': str(uuid.uuid4()),
                'name': data.get('name'),
                'email': data.get('email'),
                'whatsapp': data.get('whatsapp'),
                'password': data.get('password', 'temp123'),
                'role': 'worker',
                'hourly_rate': safe_float(data.get('hourly_rate', 10)),
                'worker_percentage': safe_float(data.get('worker_percentage', 10)),
                'created_at': datetime.utcnow().isoformat()
            }
            result = supabase_request('POST', 'hs_users', data=worker_data)
            return jsonify({'success': True, 'data': result['data'], 'message': 'Worker added successfully!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'PUT':
        try:
            data = request.get_json()
            worker_id = data.get('id')
            if not worker_id:
                return jsonify({'success': False, 'error': 'Worker ID required'}), 400
            
            update_data = {
                'name': data.get('name'),
                'email': data.get('email'),
                'whatsapp': data.get('whatsapp'),
                'hourly_rate': safe_float(data.get('hourly_rate', 10)),
                'worker_percentage': safe_float(data.get('worker_percentage', 10)),
                'updated_at': datetime.utcnow().isoformat()
            }
            
            if data.get('password') and data.get('password') != '********':
                update_data['password'] = data.get('password')
            
            result = supabase_request('PATCH', 'hs_users', data=update_data, filters={'id': worker_id})
            return jsonify({'success': True, 'data': result['data'], 'message': 'Worker updated successfully!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'DELETE':
        try:
            worker_id = request.args.get('id')
            if not worker_id:
                return jsonify({'success': False, 'error': 'Worker ID required'}), 400
            supabase_request('DELETE', 'hs_worker_assignments', filters={'worker_id': worker_id})
            supabase_request('DELETE', 'hs_users', filters={'id': worker_id})
            return jsonify({'success': True, 'message': 'Worker deleted successfully!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# ASSIGNMENTS
# ============================================================

@app.route('/assignments')
@login_required
@admin_required
def assignments():
    try:
        workers_data = supabase_request('GET', 'hs_users', filters={'role': 'worker'})
        accounts_data = supabase_request('GET', 'hs_accounts')
        assignments_data = supabase_request('GET', 'hs_worker_assignments')
        proxies_data = supabase_request('GET', 'hs_proxies')
        
        proxy_dict = {}
        if proxies_data['data']:
            for p in proxies_data['data']:
                proxy_dict[p['id']] = p
        
        account_dict = {}
        if accounts_data['data']:
            for acc in accounts_data['data']:
                acc['proxy_info'] = None
                if acc.get('proxy_id') and acc['proxy_id'] in proxy_dict:
                    acc['proxy_info'] = proxy_dict[acc['proxy_id']]
                account_dict[acc['id']] = acc
        
        assignment_map = {}
        if assignments_data['data']:
            for a in assignments_data['data']:
                if a['worker_id'] not in assignment_map:
                    assignment_map[a['worker_id']] = []
                assignment_map[a['worker_id']].append(a['account_id'])
        
        if workers_data['data']:
            for w in workers_data['data']:
                w['assigned_accounts'] = []
                for acc_id in assignment_map.get(w['id'], []):
                    if acc_id in account_dict:
                        w['assigned_accounts'].append(account_dict[acc_id])
        
        return render_template('assignments.html', 
            workers=workers_data['data'] if workers_data['data'] else [],
            accounts=accounts_data['data'] if accounts_data['data'] else [],
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return render_template('assignments.html', workers=[], accounts=[], user_name=session.get('user_name'), now=datetime.now(), stats=get_handshake_stats())

@app.route('/api/worker-assignments', methods=['GET', 'POST', 'DELETE'])
@login_required
@admin_required
def api_worker_assignments():
    if request.method == 'GET':
        try:
            worker_id = request.args.get('worker_id')
            if worker_id:
                result = supabase_request('GET', 'hs_worker_assignments', filters={'worker_id': worker_id})
            else:
                result = supabase_request('GET', 'hs_worker_assignments')
            return jsonify({'success': True, 'data': result['data']})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            worker_id = data.get('worker_id')
            account_ids = data.get('account_ids', [])
            
            if not worker_id:
                return jsonify({'success': False, 'error': 'Worker ID required'}), 400
            
            supabase_request('DELETE', 'hs_worker_assignments', filters={'worker_id': worker_id})
            
            for acc_id in account_ids:
                assignment = {
                    'id': str(uuid.uuid4()),
                    'worker_id': worker_id,
                    'account_id': acc_id,
                    'created_at': datetime.utcnow().isoformat()
                }
                supabase_request('POST', 'hs_worker_assignments', data=assignment)
            
            return jsonify({'success': True, 'message': 'Worker assignments updated successfully!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'DELETE':
        try:
            assignment_id = request.args.get('id')
            if not assignment_id:
                return jsonify({'success': False, 'error': 'Assignment ID required'}), 400
            supabase_request('DELETE', 'hs_worker_assignments', filters={'id': assignment_id})
            return jsonify({'success': True, 'message': 'Assignment removed successfully!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# MANAGERS
# ============================================================

@app.route('/managers')
@login_required
@admin_required
def managers():
    try:
        managers_data = supabase_request('GET', 'hs_users', filters={'role': 'manager'})
        accounts_data = supabase_request('GET', 'hs_accounts')
        return render_template('managers.html', 
            managers=managers_data['data'] if managers_data['data'] else [],
            accounts=accounts_data['data'] if accounts_data['data'] else [],
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
        return render_template('managers.html', managers=[], accounts=[], user_name=session.get('user_name'), now=datetime.now(), stats=get_handshake_stats())

@app.route('/api/managers', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
@admin_required
def api_managers():
    if request.method == 'GET':
        try:
            result = supabase_request('GET', 'hs_users', filters={'role': 'manager'})
            return jsonify({'success': True, 'data': result['data']})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            manager_data = {
                'id': str(uuid.uuid4()),
                'name': data.get('name'),
                'email': data.get('email'),
                'password': data.get('password', 'temp123'),
                'role': 'manager',
                'created_at': datetime.utcnow().isoformat()
            }
            result = supabase_request('POST', 'hs_users', data=manager_data)
            return jsonify({'success': True, 'data': result['data'], 'message': 'Manager added successfully!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'PUT':
        try:
            data = request.get_json()
            manager_id = data.get('id')
            if not manager_id:
                return jsonify({'success': False, 'error': 'Manager ID required'}), 400
            del data['id']
            data['updated_at'] = datetime.utcnow().isoformat()
            result = supabase_request('PATCH', 'hs_users', data=data, filters={'id': manager_id})
            return jsonify({'success': True, 'data': result['data'], 'message': 'Manager updated successfully!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'DELETE':
        try:
            manager_id = request.args.get('id')
            if not manager_id:
                return jsonify({'success': False, 'error': 'Manager ID required'}), 400
            supabase_request('DELETE', 'hs_manager_assignments', filters={'manager_id': manager_id})
            supabase_request('DELETE', 'hs_users', filters={'id': manager_id})
            return jsonify({'success': True, 'message': 'Manager deleted successfully!'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/manager-assignments', methods=['POST'])
@login_required
@admin_required
def api_manager_assignments():
    try:
        data = request.get_json()
        manager_id = data.get('manager_id')
        account_ids = data.get('account_ids', [])
        
        if not manager_id:
            return jsonify({'success': False, 'error': 'Manager ID required'}), 400
        
        supabase_request('DELETE', 'hs_manager_assignments', filters={'manager_id': manager_id})
        
        for acc_id in account_ids:
            assignment = {
                'id': str(uuid.uuid4()),
                'manager_id': manager_id,
                'account_id': acc_id,
                'created_at': datetime.utcnow().isoformat()
            }
            supabase_request('POST', 'hs_manager_assignments', data=assignment)
        
        return jsonify({'success': True, 'message': 'Manager assignments updated successfully!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# VERIFICATION
# ============================================================

@app.route('/verification')
@login_required
@admin_required
def verification():
    try:
        print("=" * 60)
        print("🔍 VERIFICATION PAGE LOADED")
        print("=" * 60)
        
        account_dict, worker_dict, _, _ = build_lookups()
        
        submissions_response = supabase_request('GET', 'hs_submissions')
        all_submissions = submissions_response['data'] if submissions_response['data'] else []
        
        print(f"📊 Found {len(all_submissions)} total submissions")
        print(f"👷 Found {len(worker_dict)} workers")
        print(f"📂 Found {len(account_dict)} accounts")
        
        worker_data = []
        
        for worker_id, worker in worker_dict.items():
            worker_subs = [s for s in all_submissions if s.get('worker_id') == worker_id]
            
            # ============================================================
            # 🔥 EVEN IF NO SUBMISSIONS, ADD WORKER WITH EMPTY DATA
            # ============================================================
            if not worker_subs:
                # Add worker with no submissions
                worker_data.append({
                    'worker_id': worker_id,
                    'worker_name': worker.get('name', 'Unknown'),
                    'account_name': 'No accounts',
                    'client_rate': 15,
                    'total_hours': 0,
                    'total_hours_submissions': 0,
                    'total_payment_amount': 0,
                    'total_payment_proofs': 0,
                    'expected_payment': 0,
                    'payment_difference': 0,
                    'weekly_data': [],
                    'last_hours_submission': 'Never',
                    'last_payment_submission': 'Never',
                    'hours_submissions': [],
                    'payment_submissions': [],
                    'verification_status': 'no_data',
                    'status_text': '📭 No Data',
                    'status_color': 'gray',
                    'hours_group': 'no_hours',
                    'hours_group_label': '🚫 No Hours',
                    'hours_group_color': 'gray',
                    'weeks_matched': 0,
                    'weeks_pending': 0,
                    'weeks_fraud': 0,
                    'weeks_issues': 0,
                    'total_weeks': 0
                })
                continue
            
            # ============================================================
            # 🔥 GROUP BY WEEK (Monday to Sunday)
            # ============================================================
            weekly_data = {}
            
            for s in worker_subs:
                status = s.get('status')
                if status == 'rejected':
                    continue
                
                submission_date_str = s.get('date')
                if not submission_date_str:
                    continue
                
                try:
                    submission_date = datetime.strptime(submission_date_str, '%Y-%m-%d').date()
                except:
                    continue
                
                # Calculate week (Monday to Sunday)
                week_start = submission_date - timedelta(days=submission_date.weekday())
                week_key = week_start.isoformat()
                
                if week_key not in weekly_data:
                    weekly_data[week_key] = {
                        'week_start': week_start,
                        'week_end': week_start + timedelta(days=6),
                        'hours': 0,
                        'payment': 0,
                        'hours_submissions': [],
                        'payment_submissions': [],
                        'has_hours': False,
                        'has_payment': False,
                        'client_rate': 15,
                        'account_name': 'Unknown'
                    }
                
                sub_type = s.get('submission_type', 'hours')
                account_id = s.get('account_id')
                account = account_dict.get(account_id, {})
                if account:
                    weekly_data[week_key]['account_name'] = account.get('name', 'Unknown')
                    weekly_data[week_key]['client_rate'] = account.get('client_rate', 15)
                
                if sub_type == 'hours':
                    hours = safe_float(s.get('hours', 0))
                    weekly_data[week_key]['hours'] += hours
                    weekly_data[week_key]['has_hours'] = True
                    weekly_data[week_key]['hours_submissions'].append({
                        'date': submission_date_str,
                        'hours': hours,
                        'status': status,
                        'day': submission_date.strftime('%A')
                    })
                
                elif sub_type == 'payment_proof':
                    amount = safe_float(s.get('total_earnings_usd', 0))
                    weekly_data[week_key]['payment'] += amount
                    weekly_data[week_key]['has_payment'] = True
                    weekly_data[week_key]['payment_submissions'].append({
                        'date': submission_date_str,
                        'amount': amount,
                        'status': status,
                        'reference': s.get('payment_reference', 'N/A'),
                        'screenshot': s.get('screenshot_url', ''),
                        'day': submission_date.strftime('%A')
                    })
            
            if not weekly_data:
                # Worker has submissions but all were rejected or no valid dates
                worker_data.append({
                    'worker_id': worker_id,
                    'worker_name': worker.get('name', 'Unknown'),
                    'account_name': 'No valid data',
                    'client_rate': 15,
                    'total_hours': 0,
                    'total_hours_submissions': 0,
                    'total_payment_amount': 0,
                    'total_payment_proofs': 0,
                    'expected_payment': 0,
                    'payment_difference': 0,
                    'weekly_data': [],
                    'last_hours_submission': 'Never',
                    'last_payment_submission': 'Never',
                    'hours_submissions': [],
                    'payment_submissions': [],
                    'verification_status': 'no_data',
                    'status_text': '📭 No Data',
                    'status_color': 'gray',
                    'hours_group': 'no_hours',
                    'hours_group_label': '🚫 No Hours',
                    'hours_group_color': 'gray',
                    'weeks_matched': 0,
                    'weeks_pending': 0,
                    'weeks_fraud': 0,
                    'weeks_issues': 0,
                    'total_weeks': 0
                })
                continue
            
            # ============================================================
            # 🔥 PROCESS EACH WEEK
            # ============================================================
            week_results = []
            total_hours_all = 0
            total_payment_all = 0
            total_expected_all = 0
            all_hours_subs = []
            all_payment_subs = []
            last_hours_date = None
            last_payment_date = None
            account_name = "Unknown"
            client_rate = 15
            
            for week_key, week in sorted(weekly_data.items()):
                client_rate = week['client_rate']
                expected = week['hours'] * client_rate
                difference = week['payment'] - expected
                
                # Calculate days between hours and payment
                days_between = "N/A"
                if week['has_hours'] and week['has_payment']:
                    last_hour_date = week['hours_submissions'][-1]['date'] if week['hours_submissions'] else None
                    last_payment_date = week['payment_submissions'][-1]['date'] if week['payment_submissions'] else None
                    if last_hour_date and last_payment_date:
                        try:
                            h_date = datetime.strptime(last_hour_date, '%Y-%m-%d').date()
                            p_date = datetime.strptime(last_payment_date, '%Y-%m-%d').date()
                            days_between = abs((p_date - h_date).days)
                        except:
                            pass
                
                # Determine week status
                if week['has_hours'] and week['has_payment'] and abs(difference) <= 2:
                    week_status = 'matched'
                    week_status_text = '✅ MATCHED'
                    week_status_color = 'green'
                elif week['has_hours'] and not week['has_payment']:
                    week_status = 'pending_payment'
                    week_status_text = '⏳ No Payment'
                    week_status_color = 'orange'
                elif not week['has_hours'] and week['has_payment']:
                    week_status = 'fraud'
                    week_status_text = '🚨 FRAUD! No Hours'
                    week_status_color = 'red'
                elif week['has_hours'] and week['has_payment'] and difference > 2:
                    week_status = 'overpaid'
                    week_status_text = f'⚠️ OVERPAID +${difference:.2f}'
                    week_status_color = 'yellow'
                elif week['has_hours'] and week['has_payment'] and difference < -2:
                    week_status = 'underpaid'
                    week_status_text = f'⚠️ UNDERPAID ${abs(difference):.2f}'
                    week_status_color = 'orange'
                else:
                    week_status = 'unknown'
                    week_status_text = '❓ Unknown'
                    week_status_color = 'gray'
                
                week_results.append({
                    'week_start': week['week_start'].strftime('%b %d'),
                    'week_end': week['week_end'].strftime('%b %d'),
                    'week_number': week['week_number'] if 'week_number' in week else '',
                    'hours': round(week['hours'], 2),
                    'payment': round(week['payment'], 2),
                    'expected': round(expected, 2),
                    'difference': round(difference, 2),
                    'has_hours': week['has_hours'],
                    'has_payment': week['has_payment'],
                    'status': week_status,
                    'status_text': week_status_text,
                    'status_color': week_status_color,
                    'hours_count': len(week['hours_submissions']),
                    'payment_count': len(week['payment_submissions']),
                    'hours_submissions': week['hours_submissions'],
                    'payment_submissions': week['payment_submissions'],
                    'days_between': days_between,
                    'account_name': week['account_name']
                })
                
                total_hours_all += week['hours']
                total_payment_all += week['payment']
                total_expected_all += expected
                all_hours_subs.extend(week['hours_submissions'])
                all_payment_subs.extend(week['payment_submissions'])
                
                if week['hours_submissions']:
                    last_hours_date = week['hours_submissions'][-1].get('date', 'Never')
                if week['payment_submissions']:
                    last_payment_date = week['payment_submissions'][-1].get('date', 'Never')
                
                if week['account_name'] != 'Unknown':
                    account_name = week['account_name']
                    client_rate = week['client_rate']
            
            if total_hours_all == 0 and total_payment_all == 0:
                # Worker has submissions but all are zero
                worker_data.append({
                    'worker_id': worker_id,
                    'worker_name': worker.get('name', 'Unknown'),
                    'account_name': account_name,
                    'client_rate': client_rate,
                    'total_hours': 0,
                    'total_hours_submissions': len(all_hours_subs),
                    'total_payment_amount': 0,
                    'total_payment_proofs': len(all_payment_subs),
                    'expected_payment': 0,
                    'payment_difference': 0,
                    'weekly_data': week_results,
                    'last_hours_submission': last_hours_date or 'Never',
                    'last_payment_submission': last_payment_date or 'Never',
                    'hours_submissions': all_hours_subs,
                    'payment_submissions': all_payment_subs,
                    'verification_status': 'no_data',
                    'status_text': '📭 No Data',
                    'status_color': 'gray',
                    'hours_group': 'no_hours',
                    'hours_group_label': '🚫 No Hours',
                    'hours_group_color': 'gray',
                    'weeks_matched': 0,
                    'weeks_pending': 0,
                    'weeks_fraud': 0,
                    'weeks_issues': 0,
                    'total_weeks': len(week_results)
                })
                continue
            
            # Count weeks by status
            matched_count = sum(1 for w in week_results if w['status'] == 'matched')
            pending_count = sum(1 for w in week_results if w['status'] == 'pending_payment')
            fraud_count = sum(1 for w in week_results if w['status'] == 'fraud')
            issue_count = sum(1 for w in week_results if w['status'] in ['overpaid', 'underpaid', 'unknown'])
            
            # Determine overall status
            if matched_count == len(week_results) and len(week_results) > 0:
                overall_status = 'matched'
                overall_status_text = f'✅ All {len(week_results)} Weeks Matched'
                overall_status_color = 'green'
            elif fraud_count > 0:
                overall_status = 'fraud'
                overall_status_text = f'🚨 {fraud_count} Week(s) Fraud'
                overall_status_color = 'red'
            elif issue_count > 0:
                overall_status = 'issues'
                overall_status_text = f'⚠️ {issue_count} Week(s) Issues'
                overall_status_color = 'yellow'
            elif pending_count > 0:
                overall_status = 'pending'
                overall_status_text = f'⏳ {pending_count} Week(s) Pending'
                overall_status_color = 'orange'
            else:
                overall_status = 'mixed'
                overall_status_text = '⚠️ Mixed Status'
                overall_status_color = 'yellow'
            
            # Determine hours group
            if total_hours_all == 0:
                hours_group = 'no_hours'
                group_label = '🚫 No Hours'
                group_color = 'gray'
            elif total_hours_all > 12:
                hours_group = 'high_performer'
                group_label = '⭐ High Performer (>12h)'
                group_color = 'green'
            elif total_hours_all >= 8:
                hours_group = 'good_worker'
                group_label = '✅ Good Worker (8-12h)'
                group_color = 'blue'
            else:
                hours_group = 'needs_improvement'
                group_label = '⚠️ Needs Improvement (<8h)'
                group_color = 'yellow'
            
            worker_data.append({
                'worker_id': worker_id,
                'worker_name': worker.get('name', 'Unknown'),
                'account_name': account_name,
                'client_rate': client_rate,
                'total_hours': round(total_hours_all, 2),
                'total_hours_submissions': len(all_hours_subs),
                'total_payment_amount': round(total_payment_all, 2),
                'total_payment_proofs': len(all_payment_subs),
                'expected_payment': round(total_expected_all, 2),
                'payment_difference': round(total_payment_all - total_expected_all, 2),
                'weekly_data': week_results,
                'last_hours_submission': last_hours_date or 'Never',
                'last_payment_submission': last_payment_date or 'Never',
                'hours_submissions': all_hours_subs,
                'payment_submissions': all_payment_subs,
                'verification_status': overall_status,
                'status_text': overall_status_text,
                'status_color': overall_status_color,
                'hours_group': hours_group,
                'hours_group_label': group_label,
                'hours_group_color': group_color,
                'weeks_matched': matched_count,
                'weeks_pending': pending_count,
                'weeks_fraud': fraud_count,
                'weeks_issues': issue_count,
                'total_weeks': len(week_results)
            })
        
        print(f"✅ Processed {len(worker_data)} workers with data")
        
        # Group workers
        grouped = {
            'high_performer': [],
            'good_worker': [],
            'needs_improvement': [],
            'no_hours': []
        }
        
        for w in worker_data:
            group = w.get('hours_group', 'no_hours')
            if group in grouped:
                grouped[group].append(w)
        
        for key in grouped:
            grouped[key].sort(key=lambda x: x['total_hours'], reverse=True)
        
        # Calculate stats
        total_workers = len(worker_data)
        matched_workers = sum(1 for w in worker_data if w.get('weeks_matched', 0) == w.get('total_weeks', 0) and w.get('total_weeks', 0) > 0)
        pending_payment = sum(1 for w in worker_data if w.get('weeks_pending', 0) > 0 and w.get('weeks_matched', 0) == 0)
        fraud_alerts = sum(1 for w in worker_data if w.get('weeks_fraud', 0) > 0)
        on_track_frequency = sum(1 for w in worker_data if w.get('weeks_pending', 0) == 0 and w.get('weeks_fraud', 0) == 0 and w.get('weeks_issues', 0) == 0)
        missing_hours = sum(1 for w in worker_data if w.get('total_hours') == 0 and w.get('total_weeks', 0) == 0)
        missing_payment = sum(1 for w in worker_data if w.get('total_payment_amount') == 0 and w.get('total_weeks', 0) == 0)
        
        return render_template('verification.html',
            workers=worker_data,
            grouped_workers=grouped,
            total_workers=total_workers,
            matched_workers=matched_workers,
            pending_payment=pending_payment,
            fraud_alerts=fraud_alerts,
            on_track_frequency=on_track_frequency,
            missing_hours=missing_hours,
            missing_payment=missing_payment,
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )
        
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Error loading verification: {str(e)}', 'danger')
        return render_template('verification.html',
            workers=[],
            grouped_workers={'high_performer': [], 'good_worker': [], 'needs_improvement': [], 'no_hours': []},
            total_workers=0,
            matched_workers=0,
            pending_payment=0,
            fraud_alerts=0,
            on_track_frequency=0,
            missing_hours=0,
            missing_payment=0,
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )
# ============================================================
# PAYMENT PROCESSING
# ============================================================

@app.route('/process-payments')
@login_required
@admin_required
def process_payments():
    try:
        account_dict, worker_dict, _, _ = build_lookups()
        
        submissions_data = supabase_request('GET', 'hs_submissions', 
            filters={'status': 'approved', 'submission_type': 'payment_proof'}
        )
        
        pending_payments = []
        total_amount = 0
        
        if submissions_data['data']:
            for s in submissions_data['data']:
                worker = worker_dict.get(s.get('worker_id'))
                account = account_dict.get(s.get('account_id'))
                
                pending_payments.append({
                    'id': s.get('id'),
                    'worker_id': s.get('worker_id'),
                    'worker_name': safe_str(worker.get('name', 'Unknown') if worker else 'Unknown'),
                    'worker_email': safe_str(worker.get('email', '') if worker else ''),
                    'whatsapp': safe_str(worker.get('whatsapp', '') if worker else ''),
                    'account_name': safe_str(account.get('name', 'Unknown') if account else 'Unknown'),
                    'date': safe_str(s.get('date')),
                    'amount': safe_float(s.get('total_earnings_usd')),
                    'worker_payout': safe_float(s.get('worker_payout_usd')),
                    'commission': safe_float(s.get('commission_usd')),
                    'payment_reference': safe_str(s.get('payment_reference', 'N/A')),
                    'payment_proof_url': safe_str(s.get('payment_proof_url', ''))
                })
                
                total_amount += safe_float(s.get('worker_payout_usd'))
        
        paid_data = supabase_request('GET', 'hs_submissions', 
            filters={'status': 'paid', 'submission_type': 'payment_proof'}
        )
        
        payment_history = []
        if paid_data['data']:
            for s in paid_data['data']:
                worker = worker_dict.get(s.get('worker_id'))
                payment_history.append({
                    'worker_name': safe_str(worker.get('name', 'Unknown') if worker else 'Unknown'),
                    'date': safe_str(s.get('date')),
                    'amount': safe_float(s.get('worker_payout_usd')),
                    'payment_reference': safe_str(s.get('payment_reference', 'N/A')),
                    'paid_at': safe_str(s.get('payment_confirmed_at', 'N/A'))
                })
        
        return render_template('process_payments.html',
            pending_payments=pending_payments,
            payment_history=payment_history,
            total_pending_amount=total_amount,
            pending_count=len(pending_payments),
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )
    except Exception as e:
        flash(f'Error loading payments: {str(e)}', 'danger')
        return render_template('process_payments.html',
            pending_payments=[],
            payment_history=[],
            total_pending_amount=0,
            pending_count=0,
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats()
        )

@app.route('/api/process-payment', methods=['POST'])
@login_required
@admin_required
def api_process_payment():
    try:
        data = request.get_json()
        submission_id = data.get('submission_id')
        payment_method = data.get('payment_method', 'bank')
        payment_notes = data.get('payment_notes', '')
        
        if not submission_id:
            return jsonify({'success': False, 'error': 'Submission ID required'}), 400
        
        submission = supabase_request('GET', 'hs_submissions', filters={'id': submission_id})
        if not submission['data']:
            return jsonify({'success': False, 'error': 'Submission not found'}), 404
        
        worker_payout = safe_float(submission['data'][0].get('worker_payout_usd'))
        worker_id = submission['data'][0].get('worker_id')
        
        update_data = {
            'status': 'paid',
            'payment_confirmed': True,
            'payment_confirmed_by': session['user_id'],
            'payment_confirmed_at': datetime.utcnow().isoformat(),
            'payment_method': payment_method,
            'payment_notes': payment_notes,
            'updated_at': datetime.utcnow().isoformat()
        }
        
        result = supabase_request('PATCH', 'hs_submissions', data=update_data, filters={'id': submission_id})
        
        if worker_id and worker_payout > 0:
            try:
                worker_result = supabase_request('GET', 'hs_users', filters={'id': worker_id})
                if worker_result['data']:
                    worker = worker_result['data'][0]
                    current_balance = safe_float(worker.get('total_earnings_usd', 0))
                    current_payout = safe_float(worker.get('total_payout_usd', 0))
                    
                    worker_update = {
                        'total_earnings_usd': current_balance + worker_payout,
                        'total_payout_usd': current_payout + worker_payout,
                        'updated_at': datetime.utcnow().isoformat()
                    }
                    
                    supabase_request('PATCH', 'hs_users', data=worker_update, filters={'id': worker_id})
            except Exception as e:
                print(f"⚠️ Error crediting worker: {e}")
        
        return jsonify({
            'success': True, 
            'data': result['data'], 
            'message': f'Payment processed successfully! ${worker_payout:.2f} credited to worker.'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bulk-process-payments', methods=['POST'])
@login_required
@admin_required
def api_bulk_process_payments():
    try:
        data = request.get_json()
        submission_ids = data.get('submission_ids', [])
        payment_method = data.get('payment_method', 'bank')
        payment_notes = data.get('payment_notes', '')
        
        if not submission_ids:
            return jsonify({'success': False, 'error': 'No submissions selected'}), 400
        
        processed = 0
        errors = []
        total_credited = 0
        
        for submission_id in submission_ids:
            try:
                submission = supabase_request('GET', 'hs_submissions', filters={'id': submission_id})
                if submission['data']:
                    worker_payout = safe_float(submission['data'][0].get('worker_payout_usd'))
                    worker_id = submission['data'][0].get('worker_id')
                    
                    update_data = {
                        'status': 'paid',
                        'payment_confirmed': True,
                        'payment_confirmed_by': session['user_id'],
                        'payment_confirmed_at': datetime.utcnow().isoformat(),
                        'payment_method': payment_method,
                        'payment_notes': payment_notes,
                        'updated_at': datetime.utcnow().isoformat()
                    }
                    
                    supabase_request('PATCH', 'hs_submissions', data=update_data, filters={'id': submission_id})
                    
                    if worker_id and worker_payout > 0:
                        worker_result = supabase_request('GET', 'hs_users', filters={'id': worker_id})
                        if worker_result['data']:
                            worker = worker_result['data'][0]
                            current_balance = safe_float(worker.get('total_earnings_usd', 0))
                            current_payout = safe_float(worker.get('total_payout_usd', 0))
                            
                            worker_update = {
                                'total_earnings_usd': current_balance + worker_payout,
                                'total_payout_usd': current_payout + worker_payout,
                                'updated_at': datetime.utcnow().isoformat()
                            }
                            supabase_request('PATCH', 'hs_users', data=worker_update, filters={'id': worker_id})
                            total_credited += worker_payout
                    
                    processed += 1
            except Exception as e:
                errors.append(f"Error processing {submission_id}: {str(e)}")
        
        return jsonify({
            'success': True, 
            'processed': processed,
            'total': len(submission_ids),
            'errors': errors,
            'total_credited': total_credited,
            'message': f'Successfully processed {processed} payments! Total credited: ${total_credited:.2f}'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# EXPORT REPORTS
# ============================================================

@app.route('/api/export-report/<report_type>')
@login_required
@admin_required
def export_report(report_type):
    try:
        output = io.StringIO()
        writer = csv.writer(output)
        
        if report_type == 'submissions':
            writer.writerow(['Date', 'Worker', 'Account', 'Hours', 'Type', 'Status', 'Earnings', 'Payout'])
            submissions = supabase_request('GET', 'hs_submissions')
            account_dict, worker_dict, _, _ = build_lookups()
            
            for s in submissions['data']:
                worker = worker_dict.get(s.get('worker_id'))
                account = account_dict.get(s.get('account_id'))
                writer.writerow([
                    s.get('date', 'N/A'),
                    safe_str(worker.get('name', 'Unknown') if worker else 'Unknown'),
                    safe_str(account.get('name', 'Unknown') if account else 'Unknown'),
                    safe_float(s.get('hours')),
                    s.get('submission_type', 'hours'),
                    s.get('status', 'pending'),
                    safe_float(s.get('total_earnings_usd')),
                    safe_float(s.get('worker_payout_usd'))
                ])
        
        elif report_type == 'workers':
            writer.writerow(['Name', 'Email', 'WhatsApp', 'Hourly Rate', 'Percentage', 'Assigned Accounts', 'Total Hours', 'Total Earnings'])
            workers = supabase_request('GET', 'hs_users', filters={'role': 'worker'})
            assignments = supabase_request('GET', 'hs_worker_assignments')
            submissions = supabase_request('GET', 'hs_submissions')
            
            assignment_map = {}
            for a in assignments['data']:
                if a['worker_id'] not in assignment_map:
                    assignment_map[a['worker_id']] = []
                assignment_map[a['worker_id']].append(a['account_id'])
            
            worker_totals = {}
            for s in submissions['data']:
                worker_id = s.get('worker_id')
                if worker_id not in worker_totals:
                    worker_totals[worker_id] = {'hours': 0, 'earnings': 0}
                if s.get('status') in ['paid', 'approved']:
                    worker_totals[worker_id]['hours'] += safe_float(s.get('hours'))
                    worker_totals[worker_id]['earnings'] += safe_float(s.get('worker_payout_usd'))
            
            for w in workers['data']:
                totals = worker_totals.get(w['id'], {'hours': 0, 'earnings': 0})
                writer.writerow([
                    w.get('name', 'N/A'),
                    w.get('email', 'N/A'),
                    w.get('whatsapp', 'N/A'),
                    safe_float(w.get('hourly_rate')),
                    safe_float(w.get('worker_percentage')),
                    len(assignment_map.get(w['id'], [])),
                    totals['hours'],
                    totals['earnings']
                ])
        
        elif report_type == 'accounts':
            writer.writerow(['Name', 'Platform', 'Location', 'Client Rate', 'Status', 'Proxy'])
            accounts = supabase_request('GET', 'hs_accounts')
            proxies = supabase_request('GET', 'hs_proxies')
            proxy_dict = {p['id']: p for p in proxies['data']} if proxies['data'] else {}
            
            for acc in accounts['data']:
                proxy = proxy_dict.get(acc.get('proxy_id'))
                writer.writerow([
                    acc.get('name', 'N/A'),
                    acc.get('platform', 'N/A'),
                    acc.get('location', 'N/A'),
                    safe_float(acc.get('client_rate')),
                    acc.get('status', 'active'),
                    proxy.get('ip', 'N/A') if proxy else 'None'
                ])
        
        elif report_type == 'payments':
            writer.writerow(['Date', 'Worker', 'Account', 'Amount', 'Payout', 'Commission', 'Reference', 'Status', 'Payment Date'])
            submissions = supabase_request('GET', 'hs_submissions', filters={'submission_type': 'payment_proof'})
            account_dict, worker_dict, _, _ = build_lookups()
            
            for s in submissions['data']:
                worker = worker_dict.get(s.get('worker_id'))
                account = account_dict.get(s.get('account_id'))
                writer.writerow([
                    s.get('date', 'N/A'),
                    safe_str(worker.get('name', 'Unknown') if worker else 'Unknown'),
                    safe_str(account.get('name', 'Unknown') if account else 'Unknown'),
                    safe_float(s.get('total_earnings_usd')),
                    safe_float(s.get('worker_payout_usd')),
                    safe_float(s.get('commission_usd')),
                    s.get('payment_reference', 'N/A'),
                    s.get('status', 'pending'),
                    s.get('payment_confirmed_at', 'N/A')
                ])
        
        else:
            return jsonify({'success': False, 'error': 'Invalid report type'}), 400
        
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'{report_type}_report_{datetime.utcnow().strftime("%Y%m%d")}.csv'
        )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# ANNOUNCEMENTS
# ============================================================

# ============================================================
# ANNOUNCEMENTS
# ============================================================

# ============================================================
# ANNOUNCEMENTS
# ============================================================

@app.route('/announcements')
@login_required
def announcements():
    """Display announcements page - accessible to all logged-in users"""
    try:
        user_id = session.get('user_id')
        user_role = session.get('user_role', 'worker')
        user_name = session.get('user_name', 'User')
        user_email = session.get('user_email', '')
        
        print("=" * 60)
        print("📢 ANNOUNCEMENTS PAGE LOADED")
        print(f"👤 User: {user_name} ({user_role}) - ID: {user_id}")
        print("=" * 60)
        
        # Get all announcements
        announcements_response = supabase_request('GET', 'hs_announcements')
        all_announcements = announcements_response['data'] if announcements_response['data'] else []
        
        # ============================================================
        # 🔥 GET ALL USERS FOR CONTACT LIST
        # ============================================================
        users_response = supabase_request('GET', 'hs_users')
        all_users = users_response['data'] if users_response['data'] else []
        
        print(f"📊 Total announcements: {len(all_announcements)}")
        print(f"👥 Total users: {len(all_users)}")
        
        # Process announcements for display
        processed_announcements = []
        for announcement in all_announcements:
            try:
                # Get the message
                message_text = announcement.get('message') or announcement.get('content') or announcement.get('text') or ''
                
                # Parse read_by
                read_by = announcement.get('read_by', '[]')
                if isinstance(read_by, str):
                    read_by = json.loads(read_by) if read_by else []
                elif not isinstance(read_by, list):
                    read_by = []
                
                # Parse target_users
                target_users = announcement.get('target_users', '[]')
                if isinstance(target_users, str):
                    target_users = json.loads(target_users) if target_users else []
                elif not isinstance(target_users, list):
                    target_users = []
                
                # Get sender info
                sender_id = announcement.get('created_by') or 'admin'
                sender_name = announcement.get('created_by_name') or 'Admin'
                sender_role = announcement.get('created_by_role') or 'Admin'
                
                # Map to template-friendly field names
                processed = {
                    'id': announcement.get('id'),
                    'title': announcement.get('title', 'No Title'),
                    'content': message_text,
                    'message': message_text,
                    'audience': announcement.get('audience', 'all'),
                    'target_users': target_users,
                    'read_by': read_by,
                    'sender_id': sender_id,
                    'sender_name': sender_name,
                    'sender_role': sender_role,
                    'priority': announcement.get('priority', 'normal'),
                    'recipient_type': 'all_users',
                    'created_at': announcement.get('created_at', datetime.utcnow().isoformat()),
                    'updated_at': announcement.get('updated_at', datetime.utcnow().isoformat()),
                    'is_read': user_id in read_by if user_id else False
                }
                
                # Determine recipient type from audience
                audience = processed['audience']
                if audience == 'all':
                    processed['recipient_type'] = 'all_users'
                elif audience == 'workers':
                    processed['recipient_type'] = 'all_workers'
                elif audience == 'admins':
                    processed['recipient_type'] = 'all_admins'
                else:
                    processed['recipient_type'] = 'all_users'
                
                processed_announcements.append(processed)
                
            except Exception as e:
                print(f"⚠️ Error processing announcement: {e}")
                message_text = announcement.get('message') or announcement.get('content') or announcement.get('text') or ''
                processed = {
                    'id': announcement.get('id'),
                    'title': announcement.get('title', 'No Title'),
                    'content': message_text,
                    'message': message_text,
                    'audience': 'all',
                    'target_users': [],
                    'read_by': [],
                    'sender_id': 'admin',
                    'sender_name': 'Admin',
                    'sender_role': 'Admin',
                    'priority': 'normal',
                    'recipient_type': 'all_users',
                    'created_at': announcement.get('created_at', datetime.utcnow().isoformat()),
                    'updated_at': announcement.get('updated_at', datetime.utcnow().isoformat()),
                    'is_read': False
                }
                processed_announcements.append(processed)
        
        # Sort by created_at descending (newest first)
        processed_announcements = sorted(processed_announcements, 
                                       key=lambda x: x.get('created_at', ''), 
                                       reverse=True)
        
        # ============================================================
        # 🔥 FILTERING LOGIC
        # ============================================================
        filtered_announcements = []
        for announcement in processed_announcements:
            audience = announcement.get('audience', 'all')
            target_users = announcement.get('target_users', [])
            
            if audience == 'all':
                filtered_announcements.append(announcement)
            elif audience == 'workers' and user_role == 'worker':
                filtered_announcements.append(announcement)
            elif audience == 'admins' and user_role in ['admin', 'manager']:
                filtered_announcements.append(announcement)
            elif user_id in target_users:
                filtered_announcements.append(announcement)
        
        print(f"📊 Showing {len(filtered_announcements)} announcements after filtering")
        
        # Mark announcements as read
        for announcement in filtered_announcements:
            try:
                read_by = announcement.get('read_by', [])
                if user_id and user_id not in read_by:
                    read_by.append(user_id)
                    supabase_request('PATCH', 'hs_announcements', 
                        data={'read_by': json.dumps(read_by)},
                        filters={'id': announcement['id']}
                    )
                    announcement['is_read'] = True
            except Exception as e:
                print(f"⚠️ Error marking announcement as read: {e}")
        
        # Get stats
        stats = get_handshake_stats()
        
        # ✅ Choose template based on user role
        if user_role == 'admin':
            template = 'announcements.html'
        else:
            template = 'worker_announcements.html'
        
        # ✅ Pass users to template
        return render_template(template,
            announcements=filtered_announcements,
            users=all_users,  # ← ADD THIS
            current_user_id=user_id,
            current_user_role=user_role,
            user_name=user_name,
            user_email=user_email,
            now=datetime.now(),
            stats=stats,
            is_admin=(user_role == 'admin')
        )
        
    except Exception as e:
        print(f"❌ Error in announcements route: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Error loading announcements: {str(e)}', 'danger')
        
        return render_template('worker_announcements.html',
            announcements=[],
            users=[],  # ← ADD THIS
            current_user_id=session.get('user_id'),
            current_user_role=session.get('user_role'),
            user_name=session.get('user_name'),
            now=datetime.now(),
            stats=get_handshake_stats(),
            is_admin=False
        )

@app.route('/api/announcements', methods=['GET', 'POST'])
@login_required
def api_announcements():
    """API endpoint for announcements - Chat system with role-based permissions"""
    
    if request.method == 'GET':
        try:
            result = supabase_request('GET', 'hs_announcements')
            processed = []
            for item in result['data']:
                read_by = item.get('read_by', '[]')
                if isinstance(read_by, str):
                    read_by = json.loads(read_by) if read_by else []
                else:
                    read_by = read_by or []
                
                target_users = item.get('target_users', '[]')
                if isinstance(target_users, str):
                    target_users = json.loads(target_users) if target_users else []
                else:
                    target_users = target_users or []
                
                item['read_by'] = read_by
                item['target_users'] = target_users
                processed.append(item)
            return jsonify({'success': True, 'data': processed})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'POST':
        try:
            user_role = session.get('user_role', 'worker')
            user_id = session.get('user_id')
            user_name = session.get('user_name', 'User')
            
            data = request.get_json()
            
            # Required fields
            if not data.get('title'):
                return jsonify({'success': False, 'error': 'Title is required'}), 400
            if not data.get('message'):
                return jsonify({'success': False, 'error': 'Message is required'}), 400
            
            # ============================================================
            # 🔥 RECIPIENT MAPPING - With role-based permissions
            # ============================================================
            recipient_type = data.get('recipient_type', 'all_users')
            
            # ============================================================
            # 🔥 PERMISSION CHECK - Who can send to whom
            # ============================================================
            allowed_recipients = []
            
            if user_role == 'admin':
                # Admin can send to everyone
                allowed_recipients = ['all_workers', 'all_admins', 'all_users', 'specific_worker', 'specific_admin']
            else:
                # Worker can only send to workers and all users
                allowed_recipients = ['all_workers', 'all_users', 'specific_worker']
                
                # ❌ Block workers from sending to admins
                if recipient_type in ['all_admins', 'specific_admin']:
                    return jsonify({
                        'success': False, 
                        'error': '❌ Workers cannot send messages to admins'
                    }), 403
            
            if recipient_type not in allowed_recipients:
                return jsonify({
                    'success': False, 
                    'error': f'❌ You are not allowed to send to: {recipient_type}'
                }), 403
            
            # ============================================================
            # 🔥 MAP RECIPIENT TO AUDIENCE
            # ============================================================
            audience_map = {
                'all_workers': 'workers',
                'all_admins': 'admins',
                'all_users': 'all',
                'specific_worker': 'workers',
                'specific_admin': 'admins'
            }
            audience = audience_map.get(recipient_type, 'all')
            
            print(f"📤 User: {user_name} ({user_role}) sending to: {recipient_type} → Audience: {audience}")
            
            # ============================================================
            # 🔥 GET TARGET USERS
            # ============================================================
            target_users = []
            
            if recipient_type == 'all_workers':
                try:
                    users_response = supabase_request('GET', 'hs_users', filters={'role': 'worker'})
                    if users_response['data']:
                        target_users = [u['id'] for u in users_response['data']]
                        print(f"📤 Target: {len(target_users)} workers")
                except Exception as e:
                    print(f"⚠️ Error getting workers: {e}")
                    
            elif recipient_type == 'all_admins':
                try:
                    users_response = supabase_request('GET', 'hs_users', filters={'role': 'admin'})
                    if users_response['data']:
                        target_users = [u['id'] for u in users_response['data']]
                        print(f"📤 Target: {len(target_users)} admins")
                except Exception as e:
                    print(f"⚠️ Error getting admins: {e}")
                    
            elif recipient_type == 'all_users':
                try:
                    users_response = supabase_request('GET', 'hs_users')
                    if users_response['data']:
                        target_users = [u['id'] for u in users_response['data']]
                        print(f"📤 Target: {len(target_users)} all users")
                except Exception as e:
                    print(f"⚠️ Error getting all users: {e}")
                    
            elif recipient_type in ['specific_worker', 'specific_admin']:
                recipient_id = data.get('recipient_id')
                if recipient_id:
                    target_users = [recipient_id]
                    print(f"📤 Target: 1 specific user ({recipient_id})")
            
            # ============================================================
            # 🔥 BUILD ANNOUNCEMENT DATA
            # ============================================================
            announcement_data = {
                'id': str(uuid.uuid4()),
                'title': data.get('title'),
                'message': data.get('message'),
                'audience': audience,
                'priority': data.get('priority', 'normal'),
                'target_users': json.dumps(target_users),
                'read_by': json.dumps([]),
                'created_by': user_id,
                'created_by_name': user_name,
                'created_by_role': user_role,
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }
            
            print(f"📤 Creating announcement: {announcement_data['title']}")
            print(f"📤 Audience: {announcement_data['audience']}")
            print(f"📤 Target users: {len(target_users)}")
            
            result = supabase_request('POST', 'hs_announcements', data=announcement_data)
            
            if result.get('data'):
                return jsonify({
                    'success': True,
                    'data': result['data'],
                    'message': '✅ Announcement sent successfully!',
                    'audience': audience,
                    'target_count': len(target_users)
                })
            else:
                return jsonify({'success': False, 'error': 'Failed to create announcement'}), 500
                
        except Exception as e:
            print(f"❌ Error creating announcement: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/announcements/<announcement_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def api_announcement_detail(announcement_id):
    """API endpoint for single announcement operations"""
    
    if request.method == 'GET':
        try:
            result = supabase_request('GET', 'hs_announcements', filters={'id': announcement_id})
            if result['data']:
                item = result['data'][0]
                read_by = item.get('read_by', '[]')
                if isinstance(read_by, str):
                    read_by = json.loads(read_by) if read_by else []
                else:
                    read_by = read_by or []
                
                target_users = item.get('target_users', '[]')
                if isinstance(target_users, str):
                    target_users = json.loads(target_users) if target_users else []
                else:
                    target_users = target_users or []
                
                item['read_by'] = read_by
                item['target_users'] = target_users
                return jsonify({'success': True, 'data': item})
            else:
                return jsonify({'success': False, 'error': 'Announcement not found'}), 404
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'PUT':
        try:
            if session.get('user_role') != 'admin':
                return jsonify({'success': False, 'error': 'Admin access required'}), 403
            
            data = request.get_json()
            
            check = supabase_request('GET', 'hs_announcements', filters={'id': announcement_id})
            if not check['data']:
                return jsonify({'success': False, 'error': 'Announcement not found'}), 404
            
            update_data = {
                'title': data.get('title'),
                'message': data.get('message') or data.get('content'),
                'audience': data.get('audience', 'all'),
                'priority': data.get('priority', 'normal'),
                'updated_at': datetime.utcnow().isoformat()
            }
            
            update_data = {k: v for k, v in update_data.items() if v is not None}
            
            result = supabase_request('PATCH', 'hs_announcements',
                data=update_data,
                filters={'id': announcement_id}
            )
            
            return jsonify({
                'success': True,
                'data': result['data'],
                'message': 'Announcement updated successfully!'
            })
            
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    elif request.method == 'DELETE':
        try:
            if session.get('user_role') != 'admin':
                return jsonify({'success': False, 'error': 'Admin access required'}), 403
            
            check = supabase_request('GET', 'hs_announcements', filters={'id': announcement_id})
            if not check['data']:
                return jsonify({'success': False, 'error': 'Announcement not found'}), 404
            
            supabase_request('DELETE', 'hs_announcements', filters={'id': announcement_id})
            
            return jsonify({
                'success': True,
                'message': 'Announcement deleted successfully!'
            })
            
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/announcements/<announcement_id>/read', methods=['PATCH'])
@login_required
def api_mark_announcement_read(announcement_id):
    """Mark an announcement as read for the current user"""
    try:
        user_id = session.get('user_id')
        
        announcement = supabase_request('GET', 'hs_announcements', filters={'id': announcement_id})
        if not announcement['data']:
            return jsonify({'success': False, 'error': 'Announcement not found'}), 404
        
        read_by = announcement['data'][0].get('read_by', '[]')
        if isinstance(read_by, str):
            read_by = json.loads(read_by) if read_by else []
        elif not isinstance(read_by, list):
            read_by = []
        
        if user_id not in read_by:
            read_by.append(user_id)
            supabase_request('PATCH', 'hs_announcements',
                data={'read_by': json.dumps(read_by)},
                filters={'id': announcement_id}
            )
        
        return jsonify({'success': True, 'message': 'Marked as read'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/announcements/mark-all-read', methods=['PATCH'])
@login_required
def api_mark_all_announcements_read():
    """Mark all announcements as read for the current user"""
    try:
        user_id = session.get('user_id')
        
        announcements = supabase_request('GET', 'hs_announcements')
        
        if announcements['data']:
            for announcement in announcements['data']:
                read_by = announcement.get('read_by', '[]')
                if isinstance(read_by, str):
                    read_by = json.loads(read_by) if read_by else []
                elif not isinstance(read_by, list):
                    read_by = []
                
                if user_id not in read_by:
                    read_by.append(user_id)
                    supabase_request('PATCH', 'hs_announcements',
                        data={'read_by': json.dumps(read_by)},
                        filters={'id': announcement['id']}
                    )
        
        return jsonify({'success': True, 'message': 'All announcements marked as read'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


        # ============================================================
# ADMIN MESSAGES - Real-time Chat
# ============================================================

@app.route('/admin-messages')
@login_required
@admin_required
def admin_messages():
    """Admin messages page with real-time chat"""
    try:
        user_id = session.get('user_id')
        user_name = session.get('user_name', 'Admin')
        user_email = session.get('user_email', 'admin@handshake.com')
        
        print("=" * 60)
        print("📬 ADMIN MESSAGES PAGE LOADED")
        print(f"👤 Admin: {user_name} ({user_id})")
        print("=" * 60)
        
        # Get all users (except current admin)
        users_response = supabase_request('GET', 'hs_users')
        all_users = users_response['data'] if users_response['data'] else []
        
        # Filter out current user
        filtered_users = [u for u in all_users if u.get('id') != user_id]
        
        print(f"👥 Found {len(filtered_users)} other users")
        
        # Get all announcements/messages
        announcements_response = supabase_request('GET', 'hs_announcements')
        all_announcements = announcements_response['data'] if announcements_response['data'] else []
        
        # Process messages for display
        processed_messages = []
        for msg in all_announcements:
            try:
                # Parse read_by
                read_by = msg.get('read_by', '[]')
                if isinstance(read_by, str):
                    read_by = json.loads(read_by) if read_by else []
                elif not isinstance(read_by, list):
                    read_by = []
                
                # Parse target_users
                target_users = msg.get('target_users', '[]')
                if isinstance(target_users, str):
                    target_users = json.loads(target_users) if target_users else []
                elif not isinstance(target_users, list):
                    target_users = []
                
                processed_messages.append({
                    'id': msg.get('id'),
                    'sender_id': msg.get('created_by') or msg.get('sender_id'),
                    'sender_name': msg.get('created_by_name') or msg.get('sender_name', 'Unknown'),
                    'sender_role': msg.get('created_by_role') or msg.get('sender_role', 'User'),
                    'message': msg.get('message') or msg.get('content', ''),
                    'title': msg.get('title', ''),
                    'audience': msg.get('audience', 'all'),
                    'target_users': target_users,
                    'read_by': read_by,
                    'created_at': msg.get('created_at', datetime.utcnow().isoformat()),
                    'priority': msg.get('priority', 'normal')
                })
            except Exception as e:
                print(f"⚠️ Error processing message: {e}")
                continue
        
        print(f"📊 Found {len(processed_messages)} total messages")
        
        # Get stats
        stats = get_handshake_stats()
        
        return render_template('admin_messages.html',
            users=filtered_users,
            announcements=processed_messages,
            current_user_id=user_id,
            current_user_role='admin',
            user_name=user_name,
            user_email=user_email,
            now=datetime.now(),
            stats=stats
        )
        
    except Exception as e:
        print(f"❌ Error loading admin messages: {str(e)}")
        import traceback
        traceback.print_exc()
        flash('Error loading messages', 'danger')
        return redirect(url_for('admin_dashboard'))


# ============================================================
# WORKER MESSAGES - Real-time Chat
# ============================================================

@app.route('/worker-messages')
@login_required
def worker_messages():
    """Worker messages page with real-time chat"""
    try:
        user_id = session.get('user_id')
        user_name = session.get('user_name', 'Worker')
        user_email = session.get('user_email', 'worker@handshake.com')
        user_role = session.get('user_role', 'worker')
        
        print("=" * 60)
        print("📬 WORKER MESSAGES PAGE LOADED")
        print(f"👤 Worker: {user_name} ({user_id})")
        print("=" * 60)
        
        # Get all users (except current worker)
        users_response = supabase_request('GET', 'hs_users')
        all_users = users_response['data'] if users_response['data'] else []
        
        # Filter out current user
        filtered_users = [u for u in all_users if u.get('id') != user_id]
        
        print(f"👥 Found {len(filtered_users)} other users")
        
        # Get all announcements/messages
        announcements_response = supabase_request('GET', 'hs_announcements')
        all_announcements = announcements_response['data'] if announcements_response['data'] else []
        
        # Process messages for display
        processed_messages = []
        for msg in all_announcements:
            try:
                # Parse read_by
                read_by = msg.get('read_by', '[]')
                if isinstance(read_by, str):
                    read_by = json.loads(read_by) if read_by else []
                elif not isinstance(read_by, list):
                    read_by = []
                
                # Parse target_users
                target_users = msg.get('target_users', '[]')
                if isinstance(target_users, str):
                    target_users = json.loads(target_users) if target_users else []
                elif not isinstance(target_users, list):
                    target_users = []
                
                processed_messages.append({
                    'id': msg.get('id'),
                    'sender_id': msg.get('created_by') or msg.get('sender_id'),
                    'sender_name': msg.get('created_by_name') or msg.get('sender_name', 'Unknown'),
                    'sender_role': msg.get('created_by_role') or msg.get('sender_role', 'User'),
                    'message': msg.get('message') or msg.get('content', ''),
                    'title': msg.get('title', ''),
                    'audience': msg.get('audience', 'all'),
                    'target_users': target_users,
                    'read_by': read_by,
                    'created_at': msg.get('created_at', datetime.utcnow().isoformat()),
                    'priority': msg.get('priority', 'normal')
                })
            except Exception as e:
                print(f"⚠️ Error processing message: {e}")
                continue
        
        print(f"📊 Found {len(processed_messages)} total messages")
        
        # Get stats
        stats = get_handshake_stats()
        
        return render_template('worker_messages.html',
            users=filtered_users,
            announcements=processed_messages,
            current_user_id=user_id,
            current_user_role=user_role,
            user_name=user_name,
            user_email=user_email,
            now=datetime.now(),
            stats=stats
        )
        
    except Exception as e:
        print(f"❌ Error loading worker messages: {str(e)}")
        import traceback
        traceback.print_exc()
        flash('Error loading messages', 'danger')
        return redirect(url_for('worker_dashboard'))
# ============================================================
# RUN APP
# ============================================================

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 HANDSHAKE MANAGER - COMPLETE")
    print("=" * 60)
    print("🌐 http://localhost:5000")
    print("=" * 60)
    print("🔑 QUICK LOGIN:")
    print("   👑 Admin: admin@handshake.com / admin123")
    print("   👤 Manager: manager@handshake.com / manager123")
    print("   👷 Worker: worker@handshake.com / worker123")
    print("=" * 60)
    print("📊 REPORTS AVAILABLE:")
    print("   📋 Submissions Report")
    print("   👤 Workers Report")
    print("   📂 Accounts Report")
    print("   💰 Payments Report")
    print("=" * 60)
    print("📌 FEATURES:")
    print("   ✅ Hours: 1 submission every 24 hours")
    print("   ✅ Payment Proof: 1 submission per week (7 days)")
    print("   ✅ Admin Dashboard with stats")
    print("   ✅ Worker Dashboard with assignments")
    print("   ✅ Manager Dashboard with oversight")
    print("   ✅ Full CRUD for Accounts, Workers, Managers")
    print("   ✅ Approval workflow for hours")
    print("   ✅ Payment processing & confirmation")
    print("   ✅ Verification dashboard")
    print("   ✅ Export reports to CSV")
    print("   ✅ Workers are credited when payment proofs are approved")
    print("   ✅ Fixed payment proof date validation (7 days between submissions)")
    print("   ✅ WhatsApp Click-to-Chat for sending login credentials")
    print("   ✅ Announcements system with read tracking")
    print("=" * 60)
    
    os.makedirs('static/uploads', exist_ok=True)
    app.run(debug=True, port=5000)
