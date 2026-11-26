import sqlite3
import uuid
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
            CREATE TABLE IF NOT EXISTS inscricoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evento_id INTEGER NOT NULL,
                participante_id INTEGER NOT NULL,
                codigo_bilhete TEXT UNIQUE NOT NULL,
                check_in INTEGER DEFAULT 0,
                data_inscricao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(evento_id, participante_id),
                FOREIGN KEY (evento_id) REFERENCES eventos(id),
                FOREIGN KEY (participante_id) REFERENCES utilizadores(id)
            );
        ''')

@app.route('/')
def index():
    pesquisa = request.args.get('q', '').strip()
    categoria = request.args.get('categoria', '').strip()
    
    query = '''
        SELECT e.*, u.nome as organizador_nome,
               (SELECT COUNT(*) FROM inscricoes i WHERE i.evento_id = e.id) as total_inscritos
        FROM eventos e 
        JOIN utilizadores u ON e.organizador_id = u.id 
        WHERE e.estado = 'PUBLICADO'
    '''
    params = []
    
    if pesquisa:
        query += " AND (e.titulo LIKE ? OR e.localizacao LIKE ?)"
        params.extend([f'%{pesquisa}%', f'%{pesquisa}%'])
    if categoria:
        query += " AND e.categoria = ?"
        params.append(categoria)
        
    query += " ORDER BY e.data_evento ASC"
    
    minhas_inscricoes = []
    inscritos_por_evento = {}
    
    with get_db() as conn:
        eventos = conn.execute(query, params).fetchall()
        
        if session.get('user_id'):
            # Buscar bilhetes do participante
            minhas_inscricoes = conn.execute('''
                SELECT i.*, e.titulo, e.data_evento, e.hora_evento, e.localizacao 
                FROM inscricoes i 
                JOIN eventos e ON i.evento_id = e.id 
                WHERE i.participante_id = ?
            ''', (session['user_id'],)).fetchall()
            
            # Se for organizador, buscar inscritos dos seus eventos (RF06)
            if session.get('user_perfil') == 'ORGANIZADOR':
                for ev in eventos:
                    if ev['organizador_id'] == session['user_id']:
                        lista = conn.execute('''
                            SELECT i.*, u.nome, u.email 
                            FROM inscricoes i 
                            JOIN utilizadores u ON i.participante_id = u.id 
                            WHERE i.evento_id = ?
                        ''', (ev['id'],)).fetchall()
                        inscritos_por_evento[ev['id']] = lista

    ids_inscritos = [item['evento_id'] for item in minhas_inscricoes]
    return render_template('index.html', eventos=eventos, pesquisa=pesquisa, categoria=categoria,
                           minhas_inscricoes=minhas_inscricoes, ids_inscritos=ids_inscritos,
                           inscritos_por_evento=inscritos_por_evento)

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

@app.route('/inscrever/<int:evento_id>', methods=['POST'])
def inscrever(evento_id):
    if not session.get('user_id'):
        flash('Faz login para te inscreveres num evento.', 'danger')
        return redirect(url_for('index'))
        
    with get_db() as conn:
        # Controlo transacional de lotação (RNF04)
        evento = conn.execute('SELECT capacidade_maxima FROM eventos WHERE id = ?', (evento_id,)).fetchone()
        inscritos = conn.execute('SELECT COUNT(*) as total FROM inscricoes WHERE evento_id = ?', (evento_id,)).fetchone()['total']
        
        if inscritos >= evento['capacidade_maxima']:
            flash('Lamentamos, este evento já esgotou as vagas!', 'danger')
            return redirect(url_for('index'))
            
        codigo = f"EF-{uuid.uuid4().hex[:8].upper()}"
        try:
            conn.execute('INSERT INTO inscricoes (evento_id, participante_id, codigo_bilhete) VALUES (?, ?, ?)',
                         (evento_id, session['user_id'], codigo))
            flash(f'Inscrição confirmada! O teu bilhete é {codigo}.', 'success')
        except sqlite3.IntegrityError:
            flash('Já estás inscrito neste evento.', 'danger')
            
    return redirect(url_for('index'))

@app.route('/checkin/<int:inscricao_id>', methods=['POST'])
def checkin(inscricao_id):
    if session.get('user_perfil') != 'ORGANIZADOR':
        return redirect(url_for('index'))
    with get_db() as conn:
        conn.execute('UPDATE inscricoes SET check_in = 1 WHERE id = ?', (inscricao_id,))
    flash('Presença (Check-in) validada com sucesso!', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
