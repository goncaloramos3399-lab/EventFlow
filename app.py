import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'chave_secreta_eventflow'
DB_NAME = 'eventflow.db'

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS utilizadores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                perfil TEXT NOT NULL CHECK (perfil IN ('ORGANIZADOR', 'PARTICIPANTE'))
            );
            CREATE TABLE IF NOT EXISTS eventos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organizador_id INTEGER NOT NULL,
                titulo TEXT NOT NULL,
                descricao TEXT,
                categoria TEXT,
                data_evento TEXT NOT NULL,
                hora_evento TEXT NOT NULL,
                localizacao TEXT NOT NULL,
                capacidade_maxima INTEGER NOT NULL,
                estado TEXT DEFAULT 'PUBLICADO',
                FOREIGN KEY (organizador_id) REFERENCES utilizadores(id)
            );
        ''')

@app.route('/')
def index():
    pesquisa = request.args.get('q', '').strip()
    categoria = request.args.get('categoria', '').strip()
    
    query = "SELECT e.*, u.nome as organizador_nome FROM eventos e JOIN utilizadores u ON e.organizador_id = u.id WHERE e.estado = 'PUBLICADO'"
    params = []
    
    if pesquisa:
        query += " AND (e.titulo LIKE ? OR e.localizacao LIKE ?)"
        params.extend([f'%{pesquisa}%', f'%{pesquisa}%'])
    if categoria:
        query += " AND e.categoria = ?"
        params.append(categoria)
        
    query += " ORDER BY e.data_evento ASC"
    
    with get_db() as conn:
        eventos = conn.execute(query, params).fetchall()
    return render_template('index.html', eventos=eventos, pesquisa=pesquisa, categoria=categoria)

@app.route('/registar', methods=['POST'])
def registar():
    nome = request.form['nome']
    email = request.form['email']
    password = generate_password_hash(request.form['password'])
    perfil = request.form['perfil']
    try:
        with get_db() as conn:
            conn.execute('INSERT INTO utilizadores (nome, email, password_hash, perfil) VALUES (?, ?, ?, ?)',
                         (nome, email, password, perfil))
        flash('Conta criada com sucesso! Faz login para continuar.', 'success')
    except sqlite3.IntegrityError:
        flash('Erro: Este e-mail já está registado.', 'danger')
    return redirect(url_for('index'))

@app.route('/login', methods=['POST'])
def login():
    email = request.form['email']
    password = request.form['password']
    with get_db() as conn:
        user = conn.execute('SELECT * FROM utilizadores WHERE email = ?', (email,)).fetchone()
    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['user_nome'] = user['nome']
        session['user_perfil'] = user['perfil']
        flash(f'Bem-vindo, {user["nome"]}!', 'success')
    else:
        flash('Credenciais inválidas.', 'danger')
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/criar-evento', methods=['POST'])
def criar_evento():
    if session.get('user_perfil') != 'ORGANIZADOR':
        flash('Apenas organizadores podem criar eventos.', 'danger')
        return redirect(url_for('index'))
        
    with get_db() as conn:
        conn.execute('''
            INSERT INTO eventos (organizador_id, titulo, descricao, categoria, data_evento, hora_evento, localizacao, capacidade_maxima)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            session['user_id'],
            request.form['titulo'],
            request.form['descricao'],
            request.form['categoria'],
            request.form['data_evento'],
            request.form['hora_evento'],
            request.form['localizacao'],
            int(request.form['capacidade_maxima'])
        ))
    flash('Evento publicado com sucesso!', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)